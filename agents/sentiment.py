from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

import requests

from agents.utils import merge_agent_params
from utils.data_sources import fetch_google_trends, fetch_twitter_sentiment
from utils.logger import logger
from utils.telegram_client import send_telegram_message

FEAR_GREED_API = "https://api.alternative.me/fng/"


def fetch_fear_greed() -> tuple[Optional[int], Optional[str], Optional[datetime.datetime]]:
    """Retrieve the Fear & Greed index and normalise basic fields."""
    try:
        logger.debug("[SENT] Récupération Fear & Greed Index")
        response = requests.get(FEAR_GREED_API, timeout=10)
        response.raise_for_status()
        payload: Dict[str, Any] = response.json().get("data", [{}])[0]

        score_raw = payload.get("value", "50") or "50"
        rating = payload.get("value_classification", "Neutral")
        ts_raw = payload.get("timestamp", "0") or "0"

        score = int(score_raw) if str(score_raw).isdigit() else 50
        timestamp = (
            datetime.datetime.fromtimestamp(int(ts_raw), tz=datetime.timezone.utc)
            if str(ts_raw).isdigit()
            else None
        )

        logger.debug(
            f"[SENT] FG Index récupéré: score={score}, rating={rating}, time={timestamp}"
        )
        return score, rating, timestamp

    except Exception as exc:  # pragma: no cover - network failure path
        logger.error(f"[SENT] Erreur API FG: {exc}")
        return None, None, None


# FIX 2026-02-20: Symboles crypto autorisés (étape 4.4)
_CRYPTO_KEYWORDS = ("BTC", "ETH", "SOL", "BNB", "LTC", "DOGE")

def _is_crypto(symbol: str) -> bool:
    s = (symbol or "").upper()
    return any(c in s for c in _CRYPTO_KEYWORDS)


class SentimentAgent:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, symbol: str = "BTCUSD"):
        self.cfg = cfg or {}
        self.symbol = (symbol or "BTCUSD").upper()
        defaults = {
            "fg_weight": 0.5,
            "twitter_weight": 0.3,
            "google_weight": 0.2,
            "neutral_fg": 50,
            "upper_threshold": 0.4,
            "lower_threshold": -0.4,
            "notify_telegram": True,
            "twitter_query": "(bitcoin OR btc) lang:en -is:retweet",
            "twitter_max_results": 50,
            "twitter_bearer_token": None,
            "google_keyword": "Bitcoin",
            "google_timeframe": "now 4-H",
            "google_geo": "US",
        }
        merged = merge_agent_params(self.symbol, "sentiment", defaults)
        if params:
            merged.update(params)
        self.params = merged
        logger.debug(f"[INIT] {self.__class__.__name__} params: {self.params}")

    def _compute_twitter(self) -> Dict[str, Any]:
        query_tpl = self.params.get("twitter_query", "(bitcoin OR btc) lang:en -is:retweet")
        query = query_tpl.format(symbol=self.symbol)
        try:
            data = fetch_twitter_sentiment(
                query=query,
                bearer_token=self.params.get("twitter_bearer_token"),
                max_results=int(self.params.get("twitter_max_results", 50)),
            )
            if data:
                score = float(data.get("score", 0.0) or 0.0)
                data["score"] = score
                samples = data.get("samples")
                logger.debug(
                    "[SENT] Twitter sentiment score=%.3f samples=%s",
                    score,
                    samples,
                )
                return data
        except Exception as exc:
            logger.debug(f"[SENT] Twitter sentiment fetch failed: {exc}")
        return {"score": 0.0, "samples": 0, "timestamp": datetime.datetime.now(datetime.timezone.utc)}

    def _compute_trends(self) -> Dict[str, Any]:
        keyword = self.params.get("google_keyword", "Bitcoin")
        try:
            data = fetch_google_trends(
                keyword=keyword,
                timeframe=self.params.get("google_timeframe", "now 4-H"),
                geo=self.params.get("google_geo", "US"),
            )
            if data:
                score = float(data.get("score", 0.0) or 0.0)
                data["score"] = score
                value = data.get("value")
                logger.debug("[SENT] Google Trends value=%s score=%.3f", value, score)
                return data
        except Exception as exc:
            logger.debug(f"[SENT] Google Trends fetch failed: {exc}")
        return {"score": 0.0, "value": 0.0, "timestamp": None, "keyword": keyword}

    def aggregate_sentiment(self) -> Dict[str, Any]:
        score_fg, rating, fg_time = fetch_fear_greed()

        twitter_data = self._compute_twitter()
        tw_score = float(twitter_data.get("score", 0.0))

        trends_data = self._compute_trends()
        gt_score = float(trends_data.get("score", 0.0))

        agg = 0.0
        if score_fg is not None:
            fg_neutral = max(1, float(self.params["neutral_fg"]))
            fg_normalized = (score_fg - fg_neutral) / fg_neutral
            agg += fg_normalized * float(self.params["fg_weight"])
            logger.debug(
                "[SENT] Contribution FG: %.3f * %.2f = %.3f",
                fg_normalized,
                self.params["fg_weight"],
                fg_normalized * float(self.params["fg_weight"]),
            )

        agg += tw_score * float(self.params["twitter_weight"])
        logger.debug(
            "[SENT] Contribution Twitter: %.3f * %.2f = %.3f",
            tw_score,
            self.params["twitter_weight"],
            tw_score * float(self.params["twitter_weight"]),
        )

        agg += gt_score * float(self.params["google_weight"])
        logger.debug(
            "[SENT] Contribution Google Trends: %.3f * %.2f = %.3f",
            gt_score,
            self.params["google_weight"],
            gt_score * float(self.params["google_weight"]),
        )

        trend = "stable"
        signal: Optional[str] = None
        upper = float(self.params["upper_threshold"])
        lower = float(self.params["lower_threshold"])

        if agg > upper:
            trend = "bullish"
            if rating in {"Extreme Greed", "Greed"}:
                signal = "SHORT"
        elif agg < lower:
            trend = "bearish"
            if rating in {"Extreme Greed", "Greed"}:
                signal = "SHORT" if self.params.get("contrarian", True) else "LONG"

        result = {
            "signal": signal,
            "fg_score": score_fg,
            "fg_rating": rating,
            "fg_timestamp": fg_time,
            "twitter_score": round(tw_score, 3),
            "twitter_samples": twitter_data.get("samples"),
            "google_score": round(gt_score, 3),
            "google_value": trends_data.get("value"),
            "agg_score": round(agg, 3),
            "trend": trend,
            "timestamp": fg_time or twitter_data.get("timestamp") or trends_data.get("timestamp"),
            "sources": {
                "twitter": twitter_data,
                "google_trends": trends_data,
            },
        }

        logger.debug(f"[SENT] Résultat agrégé: {result}")

        if signal and self.params.get("notify_telegram", True):
            score_txt = (
                f"FG={score_fg} ({rating}) | TW={result['twitter_score']} "
                f"(n={twitter_data.get('samples')}) | GT={result['google_score']} -> {signal}"
            )
            try:
                send_telegram_message(text=f"[SENTIMENT] {self.symbol} | {score_txt}", kind="status")
            except Exception as exc:  # pragma: no cover - runtime notification failure
                logger.warning(f"[SENT] telegram failed (ignored): {exc}")

        return result

    def generate_signal(self, bar: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.debug(f"[DEBUG] generate_signal appelé dans {self.__class__.__name__}")
        # FIX 2026-02-20: Désactiver pour non-crypto (étape 4.4)
        if not _is_crypto(self.symbol):
            logger.debug(f"[SENT] {self.symbol} non-crypto — sentiment désactivé")
            return {"signal": None, "agg_score": 0.0, "trend": "disabled", "reason": "non_crypto"}
        return self.aggregate_sentiment()

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        logger.debug(f"[DEBUG] execute appelé dans {self.__class__.__name__}")
        return self.generate_signal(*args, **kwargs)
