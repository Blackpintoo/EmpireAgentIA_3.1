# utils/advanced_sentiment.py
"""
OUTIL 4: Advanced Sentiment Analyzer (OPTIMISATION 2025-12-13)

Analyse avancée du sentiment de marché:
1. COT Data (Commitment of Traders) - Positions des institutionnels
2. Retail Sentiment (IG, Myfxbook) - Positions des particuliers
3. Options Flow - Put/Call ratio, Open Interest
4. Funding Rates (Crypto) - Sentiment des futures perpetuels

Stratégie: Suivre les institutionnels, fade le retail extrême.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import json
import os

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None


@dataclass
class SentimentConfig:
    """Configuration du sentiment analyzer"""
    # API endpoints (exemples - à remplacer par des vraies APIs)
    cot_api_url: str = ""  # CFTC COT Data
    retail_sentiment_api: str = ""  # IG/Myfxbook sentiment

    # Cache
    cache_ttl_minutes: int = 60
    cache_dir: str = "data/sentiment_cache"

    # Seuils
    extreme_long_threshold: float = 75.0   # > 75% long = extrême
    extreme_short_threshold: float = 25.0  # < 25% long = extrême
    cot_change_threshold: float = 10.0     # Changement significatif

    # Poids
    cot_weight: float = 0.4
    retail_weight: float = 0.3
    funding_weight: float = 0.2
    options_weight: float = 0.1

    # Crypto funding rates
    funding_bullish_threshold: float = 0.01   # < 0.01% = bullish
    funding_bearish_threshold: float = 0.05   # > 0.05% = bearish


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


class AdvancedSentimentAnalyzer:
    """
    Analyseur de sentiment avancé multi-sources.
    """

    def __init__(self, symbol: str, config: Optional[SentimentConfig] = None):
        self.symbol = symbol.upper()
        self.config = config or SentimentConfig()

        # Cache
        self._cot_cache: Optional[COTData] = None
        self._retail_cache: Optional[RetailSentiment] = None
        self._funding_cache: Optional[FundingRate] = None
        self._last_update: Optional[datetime] = None

        # Mapping symbole -> COT code
        self._cot_mapping = {
            "EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY",
            "AUDUSD": "AUD", "USDCAD": "CAD", "USDCHF": "CHF",
            "XAUUSD": "GOLD", "XAGUSD": "SILVER",
            "BTCUSD": "BTC", "ETHUSD": "ETH"
        }

        # Créer le répertoire de cache
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

    def _load_cached_data(self) -> bool:
        """Charge les données depuis le cache fichier"""
        cache_file = os.path.join(self.config.cache_dir, f"{self.symbol}_sentiment.json")
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)

                cache_time = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
                age_minutes = (datetime.now(timezone.utc) - cache_time.replace(tzinfo=timezone.utc)).total_seconds() / 60

                if age_minutes < self.config.cache_ttl_minutes:
                    # Restaurer les données
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
                            open_interest=data["cot"].get("open_interest", 0)
                        )

                    if "retail" in data:
                        self._retail_cache = RetailSentiment(
                            symbol=self.symbol,
                            timestamp=datetime.now(timezone.utc),
                            long_percentage=data["retail"].get("long_percentage", 50),
                            short_percentage=data["retail"].get("short_percentage", 50),
                            source=data["retail"].get("source", "cache")
                        )

                    self._last_update = cache_time.replace(tzinfo=timezone.utc)
                    return True

        except Exception as e:
            logger.debug(f"[SENTIMENT] Erreur lecture cache: {e}")

        return False

    def _save_cache(self):
        """Sauvegarde les données en cache"""
        cache_file = os.path.join(self.config.cache_dir, f"{self.symbol}_sentiment.json")
        try:
            data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": self.symbol
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
                    "open_interest": self._cot_cache.open_interest
                }

            if self._retail_cache:
                data["retail"] = {
                    "long_percentage": self._retail_cache.long_percentage,
                    "short_percentage": self._retail_cache.short_percentage,
                    "source": self._retail_cache.source
                }

            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.debug(f"[SENTIMENT] Erreur sauvegarde cache: {e}")

    def fetch_retail_sentiment(self) -> Optional[RetailSentiment]:
        """
        Récupère le sentiment retail.
        Note: Implémentation simulée - à remplacer par une vraie API.
        """
        # Simuler des données pour le développement
        # En production, utiliser une API comme IG, Myfxbook, DailyFX
        import random

        # Biais basé sur le symbole (simulation)
        base_long = {
            "EURUSD": 45, "GBPUSD": 42, "USDJPY": 55,
            "AUDUSD": 48, "XAUUSD": 60, "XAGUSD": 58,
            "BTCUSD": 65, "ETHUSD": 62
        }.get(self.symbol, 50)

        # Ajouter un peu de variation
        long_pct = max(10, min(90, base_long + random.randint(-15, 15)))

        self._retail_cache = RetailSentiment(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            long_percentage=float(long_pct),
            short_percentage=float(100 - long_pct),
            total_traders=random.randint(1000, 50000),
            source="simulated"
        )

        return self._retail_cache

    def fetch_funding_rate(self) -> Optional[FundingRate]:
        """
        Récupère le funding rate pour les crypto.
        """
        if not self.symbol.endswith("USD") or self.symbol not in ["BTCUSD", "ETHUSD"]:
            return None

        # Simulation - en production, utiliser l'API Binance/Bybit
        import random
        rate = random.uniform(-0.02, 0.08)

        self._funding_cache = FundingRate(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            rate=rate,
            predicted_rate=rate * 0.9,
            exchange="simulated"
        )

        return self._funding_cache

    def analyze(self) -> Dict[str, Any]:
        """
        Analyse complète du sentiment.

        Returns:
            Dict avec signal, score, details
        """
        result = {
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
            # Charger le cache ou récupérer les données
            if not self._is_cache_valid():
                self._load_cached_data()

            # Récupérer les données fraîches si nécessaire
            if self._retail_cache is None or not self._is_cache_valid():
                self.fetch_retail_sentiment()
                self._last_update = datetime.now(timezone.utc)
                self._save_cache()

            if self.symbol in ["BTCUSD", "ETHUSD"]:
                self.fetch_funding_rate()

            # Analyser le sentiment retail
            retail_score = 0.0
            if self._retail_cache:
                long_pct = self._retail_cache.long_percentage

                result["retail_sentiment"] = {
                    "long_pct": long_pct,
                    "short_pct": self._retail_cache.short_percentage,
                    "source": self._retail_cache.source
                }

                # Stratégie contrarian: fade le retail extrême
                if long_pct > self.config.extreme_long_threshold:
                    # Trop de retail long = bearish signal (fade)
                    retail_score = -0.5 - (long_pct - 75) / 50
                    result["contrarian_signal"] = "SHORT"
                    result["details"]["retail"] = f"Extreme long ({long_pct:.0f}%) - contrarian SHORT"
                elif long_pct < self.config.extreme_short_threshold:
                    # Trop de retail short = bullish signal (fade)
                    retail_score = 0.5 + (25 - long_pct) / 50
                    result["contrarian_signal"] = "LONG"
                    result["details"]["retail"] = f"Extreme short ({long_pct:.0f}%) - contrarian LONG"
                else:
                    # Zone neutre
                    retail_score = (50 - long_pct) / 100  # Léger contrarian
                    result["contrarian_signal"] = None
                    result["details"]["retail"] = f"Neutral zone ({long_pct:.0f}%)"

            # Analyser le funding rate (crypto)
            funding_score = 0.0
            if self._funding_cache:
                rate = self._funding_cache.rate

                result["funding_rate"] = {
                    "rate": rate,
                    "predicted": self._funding_cache.predicted_rate,
                    "exchange": self._funding_cache.exchange
                }

                if rate > self.config.funding_bearish_threshold:
                    # Funding élevé = trop de longs = bearish
                    funding_score = -0.5
                    result["details"]["funding"] = f"High funding ({rate:.3f}%) - bearish"
                elif rate < self.config.funding_bullish_threshold:
                    # Funding bas/négatif = bullish
                    funding_score = 0.5
                    result["details"]["funding"] = f"Low/negative funding ({rate:.3f}%) - bullish"
                else:
                    funding_score = 0.0
                    result["details"]["funding"] = f"Neutral funding ({rate:.3f}%)"

            # Calculer le score global
            total_weight = self.config.retail_weight
            weighted_score = retail_score * self.config.retail_weight

            if self._funding_cache:
                total_weight += self.config.funding_weight
                weighted_score += funding_score * self.config.funding_weight

            if total_weight > 0:
                result["sentiment_score"] = weighted_score / total_weight
            else:
                result["sentiment_score"] = 0.0

            # Déterminer le signal
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

            return result

        except Exception as e:
            logger.error(f"[SENTIMENT] Erreur analyse: {e}")
            return result

    def should_fade_retail(self, direction: str) -> Tuple[bool, str]:
        """
        Vérifie si on devrait fade le retail sentiment.

        Args:
            direction: Direction du trade envisagé

        Returns:
            Tuple[should_fade, reason]
        """
        if self._retail_cache is None:
            return False, "no_data"

        long_pct = self._retail_cache.long_percentage
        direction = direction.upper()

        # Si le retail est extrêmement long et on veut aller long aussi
        if long_pct > self.config.extreme_long_threshold and direction == "LONG":
            return True, f"retail_extreme_long_{long_pct:.0f}%"

        # Si le retail est extrêmement short et on veut aller short aussi
        if long_pct < self.config.extreme_short_threshold and direction == "SHORT":
            return True, f"retail_extreme_short_{long_pct:.0f}%"

        return False, "ok"


# Cache global
_sentiment_analyzers: Dict[str, AdvancedSentimentAnalyzer] = {}


def get_sentiment_analyzer(symbol: str, config: Optional[SentimentConfig] = None) -> AdvancedSentimentAnalyzer:
    """Récupère ou crée un analyseur de sentiment"""
    global _sentiment_analyzers

    symbol = symbol.upper()
    if symbol not in _sentiment_analyzers:
        _sentiment_analyzers[symbol] = AdvancedSentimentAnalyzer(symbol, config)

    return _sentiment_analyzers[symbol]


def analyze_advanced_sentiment(symbol: str, config: Optional[SentimentConfig] = None) -> Dict[str, Any]:
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
