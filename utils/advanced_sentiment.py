# utils/advanced_sentiment.py
# REFACTORED 2026-03-01: random.randint remplacé par des sources réelles
"""
OUTIL 4: Advanced Sentiment Analyzer

Analyse avancée du sentiment de marché :
1. COT Data (Commitment of Traders) - CFTC Socrata API (gratuit, sans clé)
2. Funding Rates (Crypto) - Binance Futures API (gratuit, sans clé)
3. Retail Sentiment - Désactivé (aucune source gratuite fiable)

Stratégie : Suivre les institutionnels (COT), fade le funding extrême (crypto).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import json
import os
import threading
import time

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None  # type: ignore


# ── Mapping symboles ─────────────────────────────────────────────────────────

# MT5 symbol -> Binance Futures symbol
_MT5_TO_BINANCE: Dict[str, str] = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT", "LTCUSD": "LTCUSDT", "ADAUSD": "ADAUSDT",
}

# MT5 symbol -> CFTC COT market name (pour requête Socrata)
_SYMBOL_TO_COT_QUERY: Dict[str, str] = {
    "EURUSD": "EURO FX",
    "GBPUSD": "BRITISH POUND",
    "USDJPY": "JAPANESE YEN",
    "AUDUSD": "AUSTRALIAN DOLLAR",
    "USDCAD": "CANADIAN DOLLAR",
    "USDCHF": "SWISS FRANC",
    "XAUUSD": "GOLD",
    "XAGUSD": "SILVER",
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SentimentConfig:
    """Configuration du sentiment analyzer"""
    # Cache
    cache_ttl_minutes: int = 60
    cache_dir: str = "data/sentiment_cache"
    funding_cache_ttl_seconds: float = 900.0    # 15 min
    cot_cache_ttl_seconds: float = 86400.0      # 24 h (données hebdomadaires)

    # Seuils
    extreme_long_threshold: float = 75.0   # > 75% long = extrême
    extreme_short_threshold: float = 25.0  # < 25% long = extrême
    cot_change_threshold: float = 10.0     # Changement significatif

    # Poids
    cot_weight: float = 0.4
    retail_weight: float = 0.3
    funding_weight: float = 0.2
    options_weight: float = 0.1

    # Crypto funding rates (en pourcentage : 0.01 = 0.01%)
    funding_bullish_threshold: float = 0.01
    funding_bearish_threshold: float = 0.05


@dataclass
class COTData:
    """Données COT (Commitment of Traders)"""
    symbol: str
    report_date: datetime
    # Commercials (hedgers)
    commercial_long: int = 0
    commercial_short: int = 0
    commercial_net: int = 0
    # Non-commercials (speculators/funds)
    noncommercial_long: int = 0
    noncommercial_short: int = 0
    noncommercial_net: int = 0
    # Open Interest
    open_interest: int = 0
    # Changements
    commercial_net_change: int = 0
    noncommercial_net_change: int = 0

    @property
    def speculator_ratio(self) -> float:
        """Ratio des positions spéculateurs (long vs total)"""
        total = self.noncommercial_long + self.noncommercial_short
        if total == 0:
            return 50.0
        return (self.noncommercial_long / total) * 100


@dataclass
class RetailSentiment:
    """Sentiment des traders retail"""
    symbol: str
    timestamp: datetime
    long_percentage: float = 50.0
    short_percentage: float = 50.0
    total_traders: int = 0
    source: str = "unknown"

    @property
    def is_extreme_long(self) -> bool:
        return self.long_percentage > 75

    @property
    def is_extreme_short(self) -> bool:
        return self.long_percentage < 25


@dataclass
class FundingRate:
    """Taux de funding pour les futures crypto"""
    symbol: str
    timestamp: datetime
    rate: float = 0.0
    predicted_rate: float = 0.0
    exchange: str = "unknown"


# ── Caches module-level (thread-safe) ────────────────────────────────────────

_funding_cache_lock = threading.Lock()
_funding_mem_cache: Dict[str, Tuple[float, FundingRate]] = {}

_cot_cache_lock = threading.Lock()
_cot_mem_cache: Dict[str, Tuple[float, COTData]] = {}


# ── Analyseur principal ──────────────────────────────────────────────────────

class AdvancedSentimentAnalyzer:
    """
    Analyseur de sentiment avancé multi-sources.

    Sources actives :
      - COT (forex/commodities) via CFTC Socrata API
      - Funding Rate (crypto) via Binance Futures API
      - Retail Sentiment : désactivé (aucune source gratuite fiable)
    """

    def __init__(self, symbol: str, config: Optional[SentimentConfig] = None):
        self.symbol = symbol.upper()
        self.config = config or SentimentConfig()

        # Instance-level cache
        self._cot_cache: Optional[COTData] = None
        self._retail_cache: Optional[RetailSentiment] = None
        self._funding_cache: Optional[FundingRate] = None
        self._last_update: Optional[datetime] = None

        # Mapping symbole -> COT code (legacy, conservé pour compatibilité)
        self._cot_mapping = {
            "EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY",
            "AUDUSD": "AUD", "USDCAD": "CAD", "USDCHF": "CHF",
            "XAUUSD": "GOLD", "XAGUSD": "SILVER",
            "BTCUSD": "BTC", "ETHUSD": "ETH"
        }

        os.makedirs(self.config.cache_dir, exist_ok=True)

    def _get_cot_code(self) -> Optional[str]:
        """Retourne le code COT pour le symbole"""
        return self._cot_mapping.get(self.symbol)

    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache est encore valide"""
        if self._last_update is None:
            return False
        age = (datetime.now(timezone.utc) - self._last_update).total_seconds() / 60
        return age < self.config.cache_ttl_minutes

    # ── Cache fichier ────────────────────────────────────────────────────────

    def _load_cached_data(self) -> bool:
        """Charge les données depuis le cache fichier"""
        cache_file = os.path.join(self.config.cache_dir, f"{self.symbol}_sentiment.json")
        try:
            if not os.path.exists(cache_file):
                return False
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cache_time = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
            age_minutes = (datetime.now(timezone.utc) - cache_time.replace(tzinfo=timezone.utc)).total_seconds() / 60

            if age_minutes >= self.config.cache_ttl_minutes:
                return False

            if "cot" in data:
                self._cot_cache = COTData(
                    symbol=self.symbol,
                    report_date=datetime.fromisoformat(data["cot"].get("report_date", "2000-01-01")),
                    commercial_long=data["cot"].get("commercial_long", 0),
                    commercial_short=data["cot"].get("commercial_short", 0),
                    commercial_net=data["cot"].get("commercial_net", 0),
                    noncommercial_long=data["cot"].get("noncommercial_long", 0),
                    noncommercial_short=data["cot"].get("noncommercial_short", 0),
                    noncommercial_net=data["cot"].get("noncommercial_net", 0),
                    open_interest=data["cot"].get("open_interest", 0),
                    noncommercial_net_change=data["cot"].get("noncommercial_net_change", 0),
                    commercial_net_change=data["cot"].get("commercial_net_change", 0),
                )

            if "funding" in data:
                self._funding_cache = FundingRate(
                    symbol=self.symbol,
                    timestamp=datetime.fromisoformat(data["funding"].get("timestamp", "2000-01-01")),
                    rate=data["funding"].get("rate", 0.0),
                    predicted_rate=data["funding"].get("predicted_rate", 0.0),
                    exchange=data["funding"].get("exchange", "cache"),
                )

            self._last_update = cache_time.replace(tzinfo=timezone.utc)
            return True

        except (FileNotFoundError, json.JSONDecodeError, IOError, ValueError) as e:
            logger.debug(f"[SENTIMENT] Erreur lecture cache: {e}")

        return False

    def _save_cache(self) -> None:
        """Sauvegarde les données en cache (écriture atomique)"""
        cache_file = os.path.join(self.config.cache_dir, f"{self.symbol}_sentiment.json")
        try:
            data: Dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": self.symbol,
            }

            if self._cot_cache:
                data["cot"] = {
                    "report_date": self._cot_cache.report_date.isoformat(),
                    "commercial_long": self._cot_cache.commercial_long,
                    "commercial_short": self._cot_cache.commercial_short,
                    "commercial_net": self._cot_cache.commercial_net,
                    "noncommercial_long": self._cot_cache.noncommercial_long,
                    "noncommercial_short": self._cot_cache.noncommercial_short,
                    "noncommercial_net": self._cot_cache.noncommercial_net,
                    "open_interest": self._cot_cache.open_interest,
                    "noncommercial_net_change": self._cot_cache.noncommercial_net_change,
                    "commercial_net_change": self._cot_cache.commercial_net_change,
                }

            if self._funding_cache:
                data["funding"] = {
                    "timestamp": self._funding_cache.timestamp.isoformat(),
                    "rate": self._funding_cache.rate,
                    "predicted_rate": self._funding_cache.predicted_rate,
                    "exchange": self._funding_cache.exchange,
                }

            tmp_path = cache_file + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, cache_file)

        except (IOError, OSError) as e:
            logger.debug(f"[SENTIMENT] Erreur sauvegarde cache: {e}")

    # ── Source 1 : Funding Rate (Binance Futures API) ────────────────────────

    def fetch_funding_rate(self) -> Optional[FundingRate]:
        """
        Funding rate réel depuis Binance Futures API.

        Endpoint : GET https://fapi.binance.com/fapi/v1/premiumIndex
        Gratuit, sans clé API.  Cache mémoire : 15 min.

        Returns None pour les symboles non-crypto.
        """
        binance_sym = _MT5_TO_BINANCE.get(self.symbol)
        if not binance_sym:
            return None

        if requests is None:
            logger.debug("[SENTIMENT] Module requests non disponible")
            return None

        # Cache mémoire module-level
        with _funding_cache_lock:
            cached = _funding_mem_cache.get(self.symbol)
            if cached:
                ts, data = cached
                if time.time() - ts < self.config.funding_cache_ttl_seconds:
                    self._funding_cache = data
                    return data

        try:
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": binance_sym},
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json()

            # lastFundingRate est un décimal (0.0001 = 0.01%)
            # On convertit en pourcentage pour correspondre aux seuils config
            rate_pct = float(raw.get("lastFundingRate", 0)) * 100
            interest_pct = float(raw.get("interestRate", 0)) * 100

            result = FundingRate(
                symbol=self.symbol,
                timestamp=datetime.now(timezone.utc),
                rate=rate_pct,
                predicted_rate=interest_pct,
                exchange="binance",
            )

            with _funding_cache_lock:
                _funding_mem_cache[self.symbol] = (time.time(), result)

            self._funding_cache = result
            logger.info(f"[SENTIMENT] Binance funding {self.symbol}: {rate_pct:.4f}%")
            return result

        except Exception as e:
            logger.warning(f"[SENTIMENT] Binance funding rate error ({self.symbol}): {e}")
            return None

    # ── Source 2 : Retail Sentiment (désactivé) ──────────────────────────────

    def fetch_retail_sentiment(self) -> Optional[RetailSentiment]:
        """
        Retail sentiment désactivé — aucune source gratuite fiable.

        Sources évaluées et rejetées :
          - IG Client Sentiment : nécessite compte API payant
          - Myfxbook : nécessite authentification session
          - DailyFX SSI : arrêté / payant

        Le poids retail est redistribué dynamiquement vers COT et
        funding dans analyze().

        Returns None systématiquement.
        """
        logger.debug(
            f"[SENTIMENT] Retail sentiment désactivé pour {self.symbol} "
            "(aucune API gratuite fiable)"
        )
        self._retail_cache = None
        return None

    # ── Source 3 : COT Data (CFTC Socrata API) ──────────────────────────────

    def fetch_cot_data(self) -> Optional[COTData]:
        """
        Données COT (Commitment of Traders) depuis l'API CFTC Socrata.

        Endpoint : https://publicreporting.cftc.gov/resource/6dca-aqww.json
        Gratuit, sans clé API.  Cache mémoire : 24 h (données hebdomadaires).

        Returns None pour les crypto (pas de données COT).
        """
        cot_query = _SYMBOL_TO_COT_QUERY.get(self.symbol)
        if not cot_query:
            return None

        if requests is None:
            logger.debug("[SENTIMENT] Module requests non disponible")
            return None

        # Cache mémoire module-level
        with _cot_cache_lock:
            cached = _cot_mem_cache.get(self.symbol)
            if cached:
                ts, data = cached
                if time.time() - ts < self.config.cot_cache_ttl_seconds:
                    self._cot_cache = data
                    return data

        try:
            url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
            params = {
                "$where": f"market_and_exchange_names like '%{cot_query}%'",
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": "2",
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json()

            if not rows:
                logger.debug(f"[SENTIMENT] COT: aucune donnée pour {self.symbol} ({cot_query})")
                return None

            latest = rows[0]

            # Parse positions
            nc_long = int(float(latest.get("noncomm_positions_long_all", 0)))
            nc_short = int(float(latest.get("noncomm_positions_short_all", 0)))
            c_long = int(float(latest.get("comm_positions_long_all", 0)))
            c_short = int(float(latest.get("comm_positions_short_all", 0)))
            oi = int(float(latest.get("open_interest_all", 0)))

            # Changements hebdomadaires
            nc_long_chg = int(float(latest.get("change_in_noncomm_long_all", 0)))
            nc_short_chg = int(float(latest.get("change_in_noncomm_short_all", 0)))
            c_long_chg = int(float(latest.get("change_in_comm_long_all", 0)))
            c_short_chg = int(float(latest.get("change_in_comm_short_all", 0)))

            report_date_str = latest.get("report_date_as_yyyy_mm_dd", "")
            try:
                # CFTC peut renvoyer "2026-02-24" ou "2026-02-24T00:00:00.000"
                clean_date = report_date_str[:10] if report_date_str else ""
                report_date = datetime.strptime(clean_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                report_date = datetime.now(timezone.utc)

            result = COTData(
                symbol=self.symbol,
                report_date=report_date,
                commercial_long=c_long,
                commercial_short=c_short,
                commercial_net=c_long - c_short,
                noncommercial_long=nc_long,
                noncommercial_short=nc_short,
                noncommercial_net=nc_long - nc_short,
                open_interest=oi,
                commercial_net_change=c_long_chg - c_short_chg,
                noncommercial_net_change=nc_long_chg - nc_short_chg,
            )

            with _cot_cache_lock:
                _cot_mem_cache[self.symbol] = (time.time(), result)

            self._cot_cache = result
            logger.info(
                f"[SENTIMENT] COT {self.symbol}: spec_ratio={result.speculator_ratio:.1f}%, "
                f"nc_net={result.noncommercial_net:+d}, date={report_date_str}"
            )
            return result

        except Exception as e:
            logger.warning(f"[SENTIMENT] CFTC COT error ({self.symbol}): {e}")
            return None

    # ── Analyse principale ───────────────────────────────────────────────────

    def analyze(self) -> Dict[str, Any]:
        """
        Analyse complète du sentiment.

        Sources actives :
          - COT (forex/commodities) : poids dynamique
          - Funding Rate (crypto) : poids dynamique
          - Retail : désactivé (poids redistribué)

        Returns:
            Dict avec signal, score, details
        """
        result: Dict[str, Any] = {
            "symbol": self.symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": "WAIT",
            "sentiment_score": 0.0,  # -1 (bearish) à +1 (bullish)
            "confidence": 0.0,
            "retail_sentiment": None,
            "cot_data": None,
            "funding_rate": None,
            "contrarian_signal": None,
            "institutional_bias": None,
            "details": {}
        }

        try:
            # Charger le cache fichier si cache mémoire invalide
            if not self._is_cache_valid():
                self._load_cached_data()

            # Récupérer les données fraîches si nécessaire
            if not self._is_cache_valid():
                self.fetch_cot_data()
                self.fetch_funding_rate()
                self.fetch_retail_sentiment()   # Returns None (disabled)
                self._last_update = datetime.now(timezone.utc)
                self._save_cache()

            # ── Score COT (forex/commodities) ────────────────────────────
            cot_score = 0.0
            has_cot = False
            if self._cot_cache:
                has_cot = True
                spec_ratio = self._cot_cache.speculator_ratio
                nc_net_chg = self._cot_cache.noncommercial_net_change

                result["cot_data"] = {
                    "speculator_ratio": spec_ratio,
                    "noncommercial_net": self._cot_cache.noncommercial_net,
                    "noncommercial_net_change": nc_net_chg,
                    "commercial_net": self._cot_cache.commercial_net,
                    "report_date": self._cot_cache.report_date.strftime("%Y-%m-%d"),
                }

                # Suivre les institutionnels (non-commercials / spéculateurs)
                if spec_ratio > 60:
                    cot_score = 0.3 + (spec_ratio - 60) / 100
                    result["institutional_bias"] = "LONG"
                    result["details"]["cot"] = (
                        f"Specs bullish ({spec_ratio:.0f}% long, chg={nc_net_chg:+d})"
                    )
                elif spec_ratio < 40:
                    cot_score = -0.3 - (40 - spec_ratio) / 100
                    result["institutional_bias"] = "SHORT"
                    result["details"]["cot"] = (
                        f"Specs bearish ({spec_ratio:.0f}% long, chg={nc_net_chg:+d})"
                    )
                else:
                    cot_score = (spec_ratio - 50) / 100
                    result["institutional_bias"] = None
                    result["details"]["cot"] = f"Specs neutral ({spec_ratio:.0f}% long)"

                # Bonus si changement significatif dans la même direction
                if abs(nc_net_chg) > self.config.cot_change_threshold:
                    cot_score += 0.1 if nc_net_chg > 0 else -0.1

            # ── Score Funding Rate (crypto) ──────────────────────────────
            funding_score = 0.0
            has_funding = False
            if self._funding_cache:
                has_funding = True
                rate = self._funding_cache.rate

                result["funding_rate"] = {
                    "rate": rate,
                    "predicted": self._funding_cache.predicted_rate,
                    "exchange": self._funding_cache.exchange,
                }

                if rate > self.config.funding_bearish_threshold:
                    # Funding élevé = trop de longs = bearish
                    funding_score = -0.5
                    result["details"]["funding"] = f"High funding ({rate:.4f}%) - bearish"
                elif rate < self.config.funding_bullish_threshold:
                    # Funding bas/négatif = bullish
                    funding_score = 0.5
                    result["details"]["funding"] = f"Low/negative funding ({rate:.4f}%) - bullish"
                else:
                    funding_score = 0.0
                    result["details"]["funding"] = f"Neutral funding ({rate:.4f}%)"

            # ── Retail (disabled) ────────────────────────────────────────
            result["retail_sentiment"] = None
            result["details"]["retail"] = "disabled (no free API)"

            # ── Score global (poids dynamiques) ──────────────────────────
            # Redistribuer les poids en fonction des sources disponibles
            weighted_score = 0.0
            total_weight = 0.0

            if has_cot:
                weighted_score += cot_score * self.config.cot_weight
                total_weight += self.config.cot_weight

            if has_funding:
                weighted_score += funding_score * self.config.funding_weight
                total_weight += self.config.funding_weight

            if total_weight > 0:
                result["sentiment_score"] = weighted_score / total_weight
            else:
                result["sentiment_score"] = 0.0
                result["details"]["warning"] = "no data source available"

            # ── Signal final ─────────────────────────────────────────────
            score = result["sentiment_score"]
            if score > 0.3:
                result["signal"] = "LONG"
                result["confidence"] = min(abs(score), 1.0)
            elif score < -0.3:
                result["signal"] = "SHORT"
                result["confidence"] = min(abs(score), 1.0)
            else:
                result["signal"] = "WAIT"
                result["confidence"] = 0.3

            # Contrarian signal basé sur COT extrêmes
            if has_cot and self._cot_cache:
                sr = self._cot_cache.speculator_ratio
                if sr > self.config.extreme_long_threshold:
                    result["contrarian_signal"] = "SHORT"
                elif sr < self.config.extreme_short_threshold:
                    result["contrarian_signal"] = "LONG"

            return result

        except Exception as e:
            logger.error(f"[SENTIMENT] Erreur analyse: {e}")
            return result

    def should_fade_retail(self, direction: str) -> Tuple[bool, str]:
        """
        Vérifie si on devrait fade le sentiment.

        Note : Retail sentiment est désactivé. Cette méthode utilise
        les données COT (positions spéculateurs) comme proxy.

        Args:
            direction: Direction du trade envisagé ("LONG" ou "SHORT")

        Returns:
            Tuple[should_fade, reason]
        """
        if self._cot_cache is None:
            return False, "no_data"

        spec_ratio = self._cot_cache.speculator_ratio
        direction = direction.upper()

        if spec_ratio > self.config.extreme_long_threshold and direction == "LONG":
            return True, f"specs_extreme_long_{spec_ratio:.0f}%"

        if spec_ratio < self.config.extreme_short_threshold and direction == "SHORT":
            return True, f"specs_extreme_short_{spec_ratio:.0f}%"

        return False, "ok"


# ── Cache global des analyseurs ──────────────────────────────────────────────

_sentiment_analyzers: Dict[str, AdvancedSentimentAnalyzer] = {}


def get_sentiment_analyzer(
    symbol: str, config: Optional[SentimentConfig] = None
) -> AdvancedSentimentAnalyzer:
    """Récupère ou crée un analyseur de sentiment"""
    global _sentiment_analyzers

    symbol = symbol.upper()
    if symbol not in _sentiment_analyzers:
        _sentiment_analyzers[symbol] = AdvancedSentimentAnalyzer(symbol, config)

    return _sentiment_analyzers[symbol]


def analyze_advanced_sentiment(
    symbol: str, config: Optional[SentimentConfig] = None
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour analyser le sentiment avancé.

    Args:
        symbol: Symbole à analyser
        config: Configuration optionnelle

    Returns:
        Dict avec sentiment_score, signal, contrarian_signal, details
    """
    analyzer = get_sentiment_analyzer(symbol, config)
    return analyzer.analyze()
