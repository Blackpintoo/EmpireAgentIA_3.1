# agents/news.py
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

import requests
from textblob import TextBlob

from utils.logger import logger
from utils.data_sources import aggregate_news
from agents.utils import merge_agent_params
# NOTE: on ne pousse PAS vers Telegram depuis l'agent (l'orchestrateur s'en charge)
# from utils.telegram_client import send_telegram_message  # <- volontairement non utilisé

# PHASE 2 (2025-12-17): Import sentiment avancé V2 avec FinBERT
try:
    from utils.advanced_sentiment_v2 import (
        get_sentiment_analyzer,
        analyze_news_sentiment,
        AdvancedSentimentAnalyzerV2
    )
    SENTIMENT_V2_AVAILABLE = True
except ImportError:
    SENTIMENT_V2_AVAILABLE = False
    logger.warning("[NEWS] advanced_sentiment_v2 non disponible - fallback TextBlob")


class NewsAgent:
    """
    Agrège plusieurs flux RSS/Atom, pondère par source + mots-clés,
    applique une polarité TextBlob et retourne un biais LONG/SHORT.

    Points clés:
    - en-têtes HTTP réalistes
    - retry léger + fallback feedparser direct
    - cache TTL par flux (évite requêtes répétées / multi-symboles)
    - throttle des warnings (évite spam logs)
    - toutes les dates en timezone UTC
    - pas d’envoi Telegram direct (laisser l’orchestrateur décider)
    """

    def __init__(self, symbol: str = "BTCUSD", cfg: Optional[dict] = None, params: Optional[dict] = None):
        self.symbol = (symbol or "BTCUSD").upper()
        cfg = cfg or {}
        defaults = {
            # ⚠️ DailyHodl retiré – flux trop instable / ratelimit
            "news_feeds": [
                "https://www.coindesk.com/arc/outboundfeeds/rss/",
                "https://cointelegraph.com/rss",
                "https://bitcoinmagazine.com/feed",   # <- remplace /.rss
                "https://finance.yahoo.com/rss/topstories",
                "https://cryptoslate.com/feed/",
                "https://coinjournal.net/news/feed/",
                "https://news.google.com/rss/search?q=bitcoin"
            ],
            "source_weight": {
                "coindesk": 3, "cointelegraph": 3, "bitcoinmagazine": 2,
                "yahoo": 1, "cryptoslate": 1, "coinjournal": 1, "google": 1
            },
            "keywords_bullish": [
                "etf","adoption","regulation","bullish","uptrend","buy","growth","rally",
                "approval","partnership","institutional","invest","expansion","spot etf","sec approval"
            ],
            "keywords_bearish": [
                "hack","ban","scam","bearish","downtrend","sell","collapse","fraud",
                "lawsuit","liquidation","delisting","sec charges","probe","freeze"
            ],
            "sentiment_threshold": 0.15,
            "keyword_weight": 2.0,
            "signal_threshold": 2.0,
            "lookback_hours": 12,

            # Réseau / stabilité
            "http_timeout": 8,
            "retry": 0,               # éviter d’allonger les jobs; fallback feedparser pris en charge
            "sleep_between": 0.15,
            "max_per_feed": 15,
            "max_news_items": 60,
            "enable_coindesk": True,
            "enable_reuters": True,
            "enable_cryptopanic": False,
            "cryptopanic_limit": 30,
            "cryptopanic_currencies": [self.symbol[:3]],

            # Anti-spam / perf
            "cache_ttl": 900,         # 15 min de cache par URL
            "warn_every": 600,        # pas plus d’1 warning/URL/10 min
            "notify_telegram": False, # l’agent ne notifie pas lui-même
            "macro_block": True,      # active le blocage macro <1h si détection
        }
        merged = merge_agent_params(self.symbol, "news", defaults)
        if params:
            merged.update(params)
        self.params = merged
        self._session = requests.Session()

    # -----------------------------
    # Utils
    # -----------------------------
    @staticmethod
    def _clean(s: str) -> str:
        return (s or "").strip().lower()

    @staticmethod
    def _sent(text: str) -> float:
        try:
            return TextBlob(text).sentiment.polarity
        except Exception:
            return 0.0

    # -----------------------------
    # Pipeline
    # -----------------------------
    def fetch_news(self) -> List[Dict[str, Any]]:
        try:
            entries = aggregate_news(self.symbol, self.params)
        except Exception as exc:
            logger.error(f"[NEWS] aggregate_news failed: {exc}")
            return []

        max_items = int(self.params.get("max_news_items", 50))
        if max_items > 0:
            entries = entries[:max_items]

        logger.debug(f"[NEWS] TOTAL={len(entries)}")
        return entries

    @staticmethod
    def dedup(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        res = []
        for e in entries:
            title = (e.get("title") or "")
            key = NewsAgent._clean(title) or (e.get("link") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            res.append(e)
        return res

    def analyze(self, entries: List[Dict[str, Any]]):
        bull = bear = tot = 0.0
        top = {"bull": [], "bear": []}

        now = dt.datetime.now(dt.timezone.utc)
        lb_sec = float(self.params["lookback_hours"]) * 3600.0
        sent_th = float(self.params["sentiment_threshold"])
        kw_w = float(self.params["keyword_weight"])

        for e in entries:
            pub = e.get("published_dt")
            if pub and (now - pub).total_seconds() > lb_sec:
                continue

            title = e.get("title", "")
            title_clean = self._clean(title)
            w = float(self.params["source_weight"].get(e.get("source", "other"), 1))

            tagged = False
            if any(k in title_clean for k in self.params["keywords_bullish"]):
                bull += kw_w * w
                top["bull"].append(title or "")
                tagged = True
            if any(k in title_clean for k in self.params["keywords_bearish"]):
                bear += kw_w * w
                top["bear"].append(title or "")
                tagged = True

            s = self._sent(title or "")
            if tagged:
                s *= 0.5  # si mot-clé, on réduit le poids du sentiment pur (double compte)
            if s > sent_th:
                bull += s * w
            elif s < -sent_th:
                bear += (-s) * w

            tot += abs(s) * w

        return bull, bear, tot, top

    # (facultatif) petit coupe-circuit macro simple
    def _has_macro_event(self) -> bool:
        if not self.params.get("macro_block", True):
            return False
        try:
            # Ex: FXStreet free endpoint (non garanti) — on ignore les erreurs
            today = dt.date.today().isoformat()
            url = f"https://calendar-api.fxstreet.com/events?from={today}&to={today}"
            r = self._session.get(url, timeout=6)
            if r.status_code != 200:
                return False
            events = r.json()
            now = dt.datetime.now(dt.timezone.utc)
            for ev in events:
                title = (ev.get("title") or "").lower()
                currency = (ev.get("currency") or "").upper()
                iso = ev.get("date", "")
                if currency not in ("USD",):
                    continue
                if any(k in title for k in ("fomc", "cpi", "nfp", "interest", "inflation", "powell")):
                    try:
                        when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
                        if 0 <= (when - now).total_seconds() <= 3600:
                            return True
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"[NEWS] Macro check error (ignored): {e}")
        return False

    # -----------------------------
    # PHASE 2: Analyse avec Sentiment V2 (FinBERT)
    # -----------------------------
    def _analyze_v2(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyse avancée avec FinBERT et pondération des sources.
        Retourne un dict compatible avec le format existant.
        """
        if not SENTIMENT_V2_AVAILABLE or not entries:
            return None

        try:
            # Préparer les items pour le sentiment analyzer V2
            news_items = []
            for e in entries:
                news_items.append({
                    "title": e.get("title", ""),
                    "source": e.get("source", "other"),
                    "content": e.get("summary", "")[:200] if e.get("summary") else ""
                })

            # Analyser avec sentiment V2
            result = analyze_news_sentiment(news_items, self.symbol)

            logger.debug(f"[NEWS_V2] {self.symbol}: score={result['score']:.2f} "
                        f"conf={result['confidence']:.2f} signal={result['signal']}")

            return result

        except Exception as e:
            logger.warning(f"[NEWS_V2] Erreur analyse V2: {e}")
            return None

    # -----------------------------
    # API agent
    # -----------------------------
    def generate_signal(self, bar=None):
        logger.debug(f"[DEBUG] generate_signal in {self.__class__.__name__}")
        # FIX 2026-02-20: Désactiver pour non-crypto (étape 4.5)
        _crypto_kw = ("BTC", "ETH", "SOL", "BNB", "LTC", "DOGE")
        if not any(c in self.symbol.upper() for c in _crypto_kw):
            logger.debug(f"[NEWS] {self.symbol} non-crypto — news désactivé")
            return {"signal": None, "intensity": 0.0, "reason": "non_crypto"}
        news = self.dedup(self.fetch_news())

        # PHASE 2: Essayer d'abord l'analyse V2 (FinBERT)
        use_v2 = self.params.get("use_sentiment_v2", True)
        v2_result = None
        if use_v2 and SENTIMENT_V2_AVAILABLE:
            v2_result = self._analyze_v2(news)

        # Analyse classique (fallback ou complémentaire)
        bull, bear, tot, top = self.analyze(news)

        # Combiner les résultats si V2 disponible
        if v2_result and v2_result.get("confidence", 0) > 0.3:
            # Utiliser principalement V2 avec ajustement classique
            v2_score = v2_result.get("score", 0.0)
            v2_signal = v2_result.get("signal")
            v2_confidence = v2_result.get("confidence", 0.5)

            # Score hybride: 70% V2 + 30% classique
            classic_score = (bull - bear)
            classic_normalized = classic_score / max(1, bull + bear) if (bull + bear) > 0 else 0

            hybrid_score = 0.7 * v2_score + 0.3 * classic_normalized

            thr = float(self.params["sentiment_threshold"])
            signal: Optional[str] = None
            intensity = abs(hybrid_score)

            if hybrid_score > thr:
                signal = "LONG"
            elif hybrid_score < -thr:
                signal = "SHORT"

            # Override par V2 si confiance élevée
            if v2_confidence > 0.6 and v2_signal:
                signal = v2_signal
                intensity = abs(v2_score) * v2_confidence

        else:
            # Fallback: analyse classique uniquement
            diff = bull - bear
            thr = float(self.params["signal_threshold"])
            signal: Optional[str] = None
            intensity = 0.0

            if diff > thr:
                signal = "LONG"
                intensity = diff
            elif diff < -thr:
                signal = "SHORT"
                intensity = -diff

        # Blocage macro (optionnel)
        if self._has_macro_event():
            return {
                "signal": None,
                "intensity": 0.0,
                "reason": "MACRO_BLOCK",
                "bull_score": bull,
                "bear_score": bear,
                "examples": {"bull": top["bull"][:3], "bear": top["bear"][:3]},
                "v2_analysis": v2_result,
            }

        return {
            "signal": signal,
            "intensity": intensity,
            "bull_score": bull,
            "bear_score": bear,
            "examples": {"bull": top["bull"][:3], "bear": top["bear"][:3]},
            "v2_analysis": v2_result,
            "method": "hybrid_v2" if v2_result else "classic",
        }

    # Alias
    def run(self, *_, **__):
        return self.generate_signal()

    def execute(self, *_, **__):
        return self.generate_signal()
