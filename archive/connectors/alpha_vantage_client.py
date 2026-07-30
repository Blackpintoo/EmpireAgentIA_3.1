"""
PHASE 5 - Alpha Vantage API Client
Provides news & sentiment data from Alpha Vantage

Documentation: https://www.alphavantage.co/documentation/
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

import requests

from utils.logger import logger


class AlphaVantageClient:
    """
    Client pour l'API Alpha Vantage

    Fonctionnalités:
    - News & Sentiment (actualités avec scores de sentiment)
    - Market news by ticker
    - Sentiment analysis (bullish/bearish scores)

    Limites API (FREE tier):
    - 25 API calls / day
    - 5 API calls / minute
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialise le client Alpha Vantage

        Args:
            api_key: Clé API Alpha Vantage (obtenir sur https://www.alphavantage.co/support/#api-key)
        """
        self.api_key = api_key
        self.session = requests.Session()
        self._last_call = 0
        self._min_interval = 12.0  # 12 seconds between calls (5 calls/min max)
        self._daily_calls = 0
        self._daily_limit = 25

        if not self.api_key:
            logger.warning("[AlphaVantage] No API key provided - client will not work")

    def _rate_limit(self):
        """Rate limiting pour respecter les limites API"""
        if self._daily_calls >= self._daily_limit:
            logger.error(f"[AlphaVantage] Daily limit of {self._daily_limit} calls reached")
            raise Exception("Alpha Vantage daily API limit reached")

        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            logger.debug(f"[AlphaVantage] Rate limiting: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self._last_call = time.time()

    def _get(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Effectue une requête GET vers l'API Alpha Vantage

        Args:
            params: Paramètres de la requête

        Returns:
            Réponse JSON ou None en cas d'erreur
        """
        if not self.api_key:
            logger.error("[AlphaVantage] Cannot make API call without API key")
            return None

        self._rate_limit()
        self._daily_calls += 1

        params["apikey"] = self.api_key

        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            # Check for API error messages
            if "Error Message" in data:
                logger.error(f"[AlphaVantage] API error: {data['Error Message']}")
                return None
            if "Note" in data:
                logger.warning(f"[AlphaVantage] API note: {data['Note']}")
                return None

            return data
        except requests.exceptions.HTTPError as e:
            logger.error(f"[AlphaVantage] HTTP error {response.status_code}: {e}")
            return None
        except Exception as e:
            logger.error(f"[AlphaVantage] Request failed: {e}")
            return None

    # ========================================================================
    # News & Sentiment
    # ========================================================================

    def get_news_sentiment(
        self,
        tickers: Optional[str] = None,
        topics: Optional[str] = None,
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
        sort: str = "LATEST",
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Récupère les actualités avec scores de sentiment

        Args:
            tickers: Symboles séparés par virgule (ex: "AAPL,MSFT" ou "CRYPTO:BTC")
            topics: Topics (blockchain, earnings, technology, finance, etc.)
            time_from: Date de début (format: YYYYMMDDThhmm)
            time_to: Date de fin
            sort: Tri (LATEST, EARLIEST, RELEVANCE)
            limit: Nombre max d'articles (1-1000, défaut: 50)

        Returns:
            {
                "items": "50",
                "sentiment_score_definition": "...",
                "relevance_score_definition": "...",
                "feed": [
                    {
                        "title": "...",
                        "url": "...",
                        "time_published": "20250115T133000",
                        "authors": [...],
                        "summary": "...",
                        "banner_image": "...",
                        "source": "Bloomberg",
                        "category_within_source": "Markets",
                        "source_domain": "bloomberg.com",
                        "topics": [...],
                        "overall_sentiment_score": 0.234567,
                        "overall_sentiment_label": "Bullish",
                        "ticker_sentiment": [
                            {
                                "ticker": "AAPL",
                                "relevance_score": "0.9",
                                "ticker_sentiment_score": "0.15",
                                "ticker_sentiment_label": "Bullish"
                            }
                        ]
                    },
                    ...
                ]
            }
        """
        params = {
            "function": "NEWS_SENTIMENT",
            "limit": min(limit, 1000)
        }

        if tickers:
            params["tickers"] = tickers
        if topics:
            params["topics"] = topics
        if time_from:
            params["time_from"] = time_from.strftime("%Y%m%dT%H%M")
        if time_to:
            params["time_to"] = time_to.strftime("%Y%m%dT%H%M")
        if sort:
            params["sort"] = sort

        result = self._get(params)
        if result and "feed" in result:
            logger.info(f"[AlphaVantage] Retrieved {len(result['feed'])} news articles with sentiment")
            return result

        logger.warning("[AlphaVantage] No news sentiment data received")
        return {"feed": [], "items": "0"}

    def get_crypto_news(
        self,
        symbols: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Récupère les actualités crypto avec sentiment

        Args:
            symbols: Liste de symboles crypto (ex: ["BTC", "ETH"])
            limit: Nombre max d'articles

        Returns:
            Liste d'articles normalisés
        """
        # Format tickers for crypto: CRYPTO:BTC, CRYPTO:ETH
        if symbols:
            tickers = ",".join([f"CRYPTO:{s.replace('USD', '').replace('USDT', '')}" for s in symbols])
        else:
            tickers = None

        # Use blockchain topic for crypto news
        result = self.get_news_sentiment(
            tickers=tickers,
            topics="blockchain,cryptocurrency",
            limit=limit
        )

        if result and "feed" in result:
            return self._normalize_news(result["feed"])

        return []

    def get_forex_news(
        self,
        pairs: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Récupère les actualités FOREX avec sentiment

        Args:
            pairs: Liste de paires FOREX (ex: ["EURUSD", "GBPUSD"])
            limit: Nombre max d'articles

        Returns:
            Liste d'articles normalisés
        """
        # Format tickers for forex: FOREX:EUR, FOREX:GBP
        if pairs:
            # Extract unique currencies from pairs
            currencies = set()
            for pair in pairs:
                if len(pair) >= 6:
                    currencies.add(pair[:3])  # EUR from EURUSD
                    currencies.add(pair[3:6])  # USD from EURUSD
            tickers = ",".join([f"FOREX:{curr}" for curr in currencies])
        else:
            tickers = None

        result = self.get_news_sentiment(
            tickers=tickers,
            topics="economy_fiscal,economy_monetary,finance",
            limit=limit
        )

        if result and "feed" in result:
            return self._normalize_news(result["feed"])

        return []

    def _normalize_news(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalise les articles de news
        Compatible avec le format attendu par NewsAgent
        """
        normalized = []

        for article in articles:
            try:
                # Parse time (format: "20250115T133000")
                time_str = article.get("time_published", "")
                published_dt = None
                if time_str:
                    try:
                        published_dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                        published_dt = published_dt.replace(tzinfo=ZoneInfo("UTC"))
                    except Exception:
                        try:
                            published_dt = datetime.strptime(time_str, "%Y%m%dT%H%M")
                            published_dt = published_dt.replace(tzinfo=ZoneInfo("UTC"))
                        except Exception as e:
                            logger.debug(f"[AlphaVantage] Failed to parse time '{time_str}': {e}")

                # Extract sentiment
                sentiment_score = article.get("overall_sentiment_score", 0.0)
                sentiment_label = article.get("overall_sentiment_label", "Neutral")

                # Convert sentiment to polarity (-1 to +1)
                try:
                    polarity = float(sentiment_score)
                except (ValueError, TypeError):
                    polarity = 0.0

                normalized.append({
                    "title": article.get("title", ""),
                    "link": article.get("url", ""),
                    "summary": article.get("summary", ""),
                    "published": published_dt.isoformat() if published_dt else time_str,
                    "published_dt": published_dt,
                    "source": article.get("source", "alphavantage"),
                    "source_domain": article.get("source_domain", ""),
                    "image": article.get("banner_image", ""),
                    "authors": article.get("authors", []),
                    "topics": article.get("topics", []),
                    "sentiment_score": sentiment_score,
                    "sentiment_label": sentiment_label,
                    "polarity": polarity,
                    "ticker_sentiment": article.get("ticker_sentiment", []),
                })
            except Exception as e:
                logger.debug(f"[AlphaVantage] Failed to normalize news article: {e}")
                continue

        return normalized

    def aggregate_sentiment(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Agrège les scores de sentiment d'une liste d'articles

        Args:
            articles: Liste d'articles (format normalisé)

        Returns:
            {
                "bullish_count": 10,
                "bearish_count": 5,
                "neutral_count": 3,
                "avg_sentiment": 0.15,
                "overall_label": "Bullish"
            }
        """
        if not articles:
            return {
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "avg_sentiment": 0.0,
                "overall_label": "Neutral"
            }

        bullish = 0
        bearish = 0
        neutral = 0
        total_sentiment = 0.0

        for article in articles:
            label = article.get("sentiment_label", "Neutral")
            score = article.get("sentiment_score", 0.0)

            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0.0

            total_sentiment += score

            if label in ("Bullish", "Somewhat-Bullish"):
                bullish += 1
            elif label in ("Bearish", "Somewhat-Bearish"):
                bearish += 1
            else:
                neutral += 1

        avg_sentiment = total_sentiment / len(articles) if articles else 0.0

        # Determine overall label
        if avg_sentiment > 0.15:
            overall_label = "Bullish"
        elif avg_sentiment < -0.15:
            overall_label = "Bearish"
        else:
            overall_label = "Neutral"

        return {
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "avg_sentiment": round(avg_sentiment, 4),
            "overall_label": overall_label,
            "total_articles": len(articles)
        }


# Singleton instance
_alpha_vantage_client: Optional[AlphaVantageClient] = None


def get_alpha_vantage_client(api_key: Optional[str] = None) -> AlphaVantageClient:
    """
    Retourne l'instance globale du AlphaVantageClient (singleton)

    Args:
        api_key: Clé API (utilisée seulement à la première initialisation)

    Returns:
        Instance de AlphaVantageClient
    """
    global _alpha_vantage_client
    if _alpha_vantage_client is None:
        _alpha_vantage_client = AlphaVantageClient(api_key)
    return _alpha_vantage_client
