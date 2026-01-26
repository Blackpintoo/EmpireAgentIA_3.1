"""
PHASE 5 - Finnhub API Client
Provides economic calendar and news data from Finnhub.io

Documentation: https://finnhub.io/docs/api/
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

import requests

from utils.logger import logger


class FinnhubClient:
    """
    Client pour l'API Finnhub

    Fonctionnalités:
    - Economic calendar (calendrier économique)
    - Market news (actualités de marché)
    - Company news (actualités d'entreprises)

    Limites API (FREE tier):
    - 60 API calls / minute
    - 30 API calls / second
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialise le client Finnhub

        Args:
            api_key: Clé API Finnhub (obtenir sur https://finnhub.io/register)
        """
        self.api_key = api_key
        self.session = requests.Session()
        self._last_call = 0
        self._min_interval = 1.0  # 1 second between calls (rate limiting)

        if not self.api_key:
            logger.warning("[Finnhub] No API key provided - client will not work")

    def _rate_limit(self):
        """Rate limiting pour respecter les limites API"""
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            time.sleep(sleep_time)
        self._last_call = time.time()

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Effectue une requête GET vers l'API Finnhub

        Args:
            endpoint: Endpoint de l'API (ex: "/calendar/economic")
            params: Paramètres de la requête

        Returns:
            Réponse JSON ou None en cas d'erreur
        """
        if not self.api_key:
            logger.error("[Finnhub] Cannot make API call without API key")
            return None

        self._rate_limit()

        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params["token"] = self.api_key

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                logger.error("[Finnhub] Rate limit exceeded")
            else:
                logger.error(f"[Finnhub] HTTP error {response.status_code}: {e}")
            return None
        except Exception as e:
            logger.error(f"[Finnhub] Request failed: {e}")
            return None

    # ========================================================================
    # Economic Calendar
    # ========================================================================

    def get_economic_calendar(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère le calendrier économique

        Args:
            start_date: Date de début (défaut: aujourd'hui)
            end_date: Date de fin (défaut: aujourd'hui + 7 jours)

        Returns:
            Liste d'événements économiques

        Format de réponse:
        [
            {
                "actual": 0.5,
                "country": "US",
                "estimate": 0.6,
                "event": "CPI YoY",
                "impact": "high",
                "prev": 0.4,
                "time": "2025-01-15 13:30:00",
                "unit": "%"
            },
            ...
        ]
        """
        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = start_date + timedelta(days=7)

        params = {
            "from": start_date.strftime("%Y-%m-%d"),
            "to": end_date.strftime("%Y-%m-%d")
        }

        result = self._get("/calendar/economic", params)
        if result and "economicCalendar" in result:
            events = result["economicCalendar"]
            logger.info(f"[Finnhub] Retrieved {len(events)} economic events")
            return self._normalize_calendar_events(events)

        logger.warning("[Finnhub] No economic calendar data received")
        return []

    def _normalize_calendar_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalise les événements du calendrier économique
        Compatible avec le format attendu par FundamentalAgent
        """
        normalized = []

        for event in events:
            try:
                # Parse time (format: "YYYY-MM-DD HH:MM:SS")
                time_str = event.get("time", "")
                event_time = None
                if time_str:
                    try:
                        event_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                        event_time = event_time.replace(tzinfo=ZoneInfo("UTC"))
                    except Exception as e:
                        logger.debug(f"[Finnhub] Failed to parse time '{time_str}': {e}")

                # Map impact (high/medium/low)
                impact = (event.get("impact", "").lower() or "medium")

                # Extract country as currency (US -> USD, GB -> GBP, etc.)
                country = event.get("country", "")
                currency = self._country_to_currency(country)

                normalized.append({
                    "event": event.get("event", "Unknown"),
                    "time": event_time.isoformat() if event_time else time_str,
                    "impact": impact,
                    "currency": currency,
                    "country": country,
                    "actual": event.get("actual"),
                    "estimate": event.get("estimate"),
                    "forecast": event.get("estimate"),  # Alias for compatibility
                    "previous": event.get("prev"),
                    "unit": event.get("unit", ""),
                    "source": "finnhub"
                })
            except Exception as e:
                logger.debug(f"[Finnhub] Failed to normalize event: {e}")
                continue

        return normalized

    @staticmethod
    def _country_to_currency(country: str) -> str:
        """Convertit un code pays en devise"""
        mapping = {
            "US": "USD",
            "GB": "GBP",
            "EU": "EUR",
            "DE": "EUR",
            "FR": "EUR",
            "IT": "EUR",
            "ES": "EUR",
            "JP": "JPY",
            "CN": "CNY",
            "AU": "AUD",
            "CA": "CAD",
            "CH": "CHF",
            "NZ": "NZD",
        }
        return mapping.get(country.upper(), country)

    # ========================================================================
    # Market News
    # ========================================================================

    def get_market_news(
        self,
        category: str = "general",
        min_id: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Récupère les actualités de marché

        Args:
            category: Catégorie (general, forex, crypto, merger)
            min_id: ID minimum pour la pagination

        Returns:
            Liste d'actualités

        Format de réponse:
        [
            {
                "category": "general",
                "datetime": 1672531200,
                "headline": "Market Update",
                "id": 123456,
                "image": "https://...",
                "related": "AAPL",
                "source": "Bloomberg",
                "summary": "...",
                "url": "https://..."
            },
            ...
        ]
        """
        params = {
            "category": category,
            "minId": min_id
        }

        result = self._get("/news", params)
        if result and isinstance(result, list):
            logger.info(f"[Finnhub] Retrieved {len(result)} news articles")
            return self._normalize_news(result)

        logger.warning("[Finnhub] No market news data received")
        return []

    def get_company_news(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère les actualités d'une entreprise/symbole

        Args:
            symbol: Symbole (ex: AAPL, TSLA)
            start_date: Date de début (défaut: 7 jours avant)
            end_date: Date de fin (défaut: aujourd'hui)

        Returns:
            Liste d'actualités
        """
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=7)

        params = {
            "symbol": symbol,
            "from": start_date.strftime("%Y-%m-%d"),
            "to": end_date.strftime("%Y-%m-%d")
        }

        result = self._get("/company-news", params)
        if result and isinstance(result, list):
            logger.info(f"[Finnhub] Retrieved {len(result)} company news for {symbol}")
            return self._normalize_news(result)

        logger.warning(f"[Finnhub] No company news for {symbol}")
        return []

    def _normalize_news(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalise les articles de news
        Compatible avec le format attendu par NewsAgent
        """
        normalized = []

        for article in articles:
            try:
                # Convert timestamp to datetime
                timestamp = article.get("datetime", 0)
                published_dt = None
                if timestamp:
                    try:
                        published_dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC"))
                    except Exception:
                        pass

                normalized.append({
                    "title": article.get("headline", ""),
                    "link": article.get("url", ""),
                    "summary": article.get("summary", ""),
                    "published": published_dt.isoformat() if published_dt else "",
                    "published_dt": published_dt,
                    "source": article.get("source", "finnhub"),
                    "image": article.get("image", ""),
                    "category": article.get("category", "general"),
                    "related_symbol": article.get("related", ""),
                })
            except Exception as e:
                logger.debug(f"[Finnhub] Failed to normalize news article: {e}")
                continue

        return normalized


# Singleton instance
_finnhub_client: Optional[FinnhubClient] = None


def get_finnhub_client(api_key: Optional[str] = None) -> FinnhubClient:
    """
    Retourne l'instance globale du FinnhubClient (singleton)

    Args:
        api_key: Clé API (utilisée seulement à la première initialisation)

    Returns:
        Instance de FinnhubClient
    """
    global _finnhub_client
    if _finnhub_client is None:
        _finnhub_client = FinnhubClient(api_key)
    return _finnhub_client
