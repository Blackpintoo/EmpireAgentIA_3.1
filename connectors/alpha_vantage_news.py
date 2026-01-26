"""
Alpha Vantage News Sentiment API Integration

API gratuite : 25 appels/jour
Documentation : https://www.alphavantage.co/documentation/#news-sentiment

Fonctionnalités :
- Récupération sentiment des news pour un symbole
- Score : -1.0 (very bearish) à +1.0 (very bullish)
- Relevance score : 0.0 à 1.0
- Cache local (30 min TTL) pour économiser les appels
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from pathlib import Path

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class AlphaVantageNews:
    """
    Client Alpha Vantage pour le sentiment des news.

    Configuration requise dans .env :
        ALPHA_VANTAGE_API_KEY=your_api_key_here

    Ou dans config.yaml :
        external_apis:
          alpha_vantage:
            enabled: true
            api_key: "your_api_key"
            cache_ttl: 1800
            rate_limit: 25
    """

    BASE_URL = "https://www.alphavantage.co/query"
    CACHE_DIR = "data/cache"
    CACHE_FILE_PREFIX = "alpha_vantage_news"
    DEFAULT_CACHE_TTL = 1800  # 30 minutes
    RATE_LIMIT_PER_DAY = 25

    # Mapping symboles vers tickers Alpha Vantage
    SYMBOL_MAPPING = {
        "BTCUSD": "CRYPTO:BTC",
        "ETHUSD": "CRYPTO:ETH",
        "BNBUSD": "CRYPTO:BNB",
        "LTCUSD": "CRYPTO:LTC",
        "ADAUSD": "CRYPTO:ADA",
        "SOLUSD": "CRYPTO:SOL",
        "EURUSD": "FOREX:EUR",
        "GBPUSD": "FOREX:GBP",
        "USDJPY": "FOREX:JPY",
        "AUDUSD": "FOREX:AUD",
        "XAUUSD": "COMMODITY:GOLD",
        "XAGUSD": "COMMODITY:SILVER",
        "CL-OIL": "COMMODITY:OIL",
        "DJ30": "EQUITY:DJI",
        "NAS100": "EQUITY:NDX",
        "GER40": "EQUITY:DAX",
    }

    def __init__(self, api_key: Optional[str] = None, cache_ttl: Optional[int] = None):
        """
        Initialise le client Alpha Vantage.

        Args:
            api_key: Clé API Alpha Vantage (ou None pour .env)
            cache_ttl: Durée du cache en secondes (défaut: 1800 = 30 min)
        """
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key:
            logger.warning("[AlphaVantage] API key manquante. Définir ALPHA_VANTAGE_API_KEY dans .env")

        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.cache_dir = Path(self.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[AlphaVantage] Initialisé avec cache TTL={self.cache_ttl}s, rate_limit={self.RATE_LIMIT_PER_DAY}/jour")

    def _get_cache_path(self, symbol: str) -> Path:
        """Retourne le chemin du fichier cache pour un symbole."""
        safe_symbol = symbol.upper().replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{self.CACHE_FILE_PREFIX}_{safe_symbol}.json"

    def _get_cache(self, symbol: str) -> Optional[Dict]:
        """Charge le cache local pour un symbole s'il existe et est valide."""
        cache_path = self._get_cache_path(symbol)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            cache_time = cache_data.get("timestamp", 0)
            now = time.time()

            if now - cache_time < self.cache_ttl:
                logger.debug(f"[AlphaVantage] Cache HIT pour {symbol} (age={int(now - cache_time)}s)")
                return cache_data.get("sentiment", {})
            else:
                logger.debug(f"[AlphaVantage] Cache EXPIRED pour {symbol} (age={int(now - cache_time)}s)")
                return None
        except Exception as e:
            logger.warning(f"[AlphaVantage] Erreur lecture cache {symbol}: {e}")
            return None

    def _set_cache(self, symbol: str, sentiment: Dict) -> None:
        """Sauvegarde le sentiment dans le cache local."""
        cache_path = self._get_cache_path(symbol)

        try:
            cache_data = {
                "timestamp": time.time(),
                "sentiment": sentiment
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"[AlphaVantage] Cache sauvegardé pour {symbol}")
        except Exception as e:
            logger.warning(f"[AlphaVantage] Erreur écriture cache {symbol}: {e}")

    def _resolve_ticker(self, symbol: str) -> str:
        """
        Convertit un symbole MT5 vers un ticker Alpha Vantage.

        Args:
            symbol: Symbole MT5 (ex: "BTCUSD", "EURUSD")

        Returns:
            Ticker Alpha Vantage (ex: "CRYPTO:BTC", "FOREX:EUR")
        """
        symbol_upper = symbol.upper()
        return self.SYMBOL_MAPPING.get(symbol_upper, symbol_upper)

    def get_news_sentiment(
        self,
        symbol: str,
        time_range: str = "24h",
        use_cache: bool = True
    ) -> Dict:
        """
        Récupère le sentiment des news pour un symbole.

        Args:
            symbol: Symbole MT5 (ex: "BTCUSD", "EURUSD")
            time_range: Plage temporelle (non utilisé par Alpha Vantage - toujours récent)
            use_cache: Utiliser le cache local si disponible

        Returns:
            Dict: {
                "symbol": "BTCUSD",
                "ticker": "CRYPTO:BTC",
                "sentiment_score": 0.35,  # -1.0 (bearish) à +1.0 (bullish)
                "relevance_score": 0.78,  # 0.0 à 1.0
                "category": "BULLISH",    # VERY_BEARISH|BEARISH|NEUTRAL|BULLISH|VERY_BULLISH
                "articles_count": 42,
                "timestamp": "2025-11-29T12:34:56Z",
                "error": None
            }
        """
        # Vérifier cache
        if use_cache:
            cached = self._get_cache(symbol)
            if cached is not None:
                return cached

        # Vérifier API key
        if not self.api_key:
            logger.error("[AlphaVantage] API key manquante")
            return self._error_response(symbol, "api_key_missing")

        # Convertir symbole
        ticker = self._resolve_ticker(symbol)

        # Appel API
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "apikey": self.api_key,
            "limit": 50,  # Nombre d'articles
            "sort": "LATEST"
        }

        try:
            logger.info(f"[AlphaVantage] Appel API pour {symbol} (ticker={ticker})")
            response = requests.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Vérifier erreurs API
            if "Error Message" in data:
                logger.error(f"[AlphaVantage] API Error: {data['Error Message']}")
                return self._error_response(symbol, data["Error Message"])

            if "Note" in data:
                # Rate limit atteint
                logger.error(f"[AlphaVantage] Rate limit: {data['Note']}")
                return self._error_response(symbol, "rate_limit_exceeded")

            # Parser feed
            feed = data.get("feed", [])
            if not feed:
                logger.warning(f"[AlphaVantage] Aucune news pour {symbol}")
                return self._neutral_response(symbol, ticker)

            # Calculer sentiment moyen
            total_sentiment = 0.0
            total_relevance = 0.0
            articles_count = 0

            for article in feed:
                # Chercher le ticker dans les ticker_sentiment
                ticker_sentiments = article.get("ticker_sentiment", [])

                for ts in ticker_sentiments:
                    if ts.get("ticker", "").upper() == ticker.upper():
                        sentiment = float(ts.get("ticker_sentiment_score", 0.0))
                        relevance = float(ts.get("relevance_score", 0.0))

                        total_sentiment += sentiment * relevance  # Pondéré par relevance
                        total_relevance += relevance
                        articles_count += 1

            if articles_count == 0 or total_relevance == 0:
                logger.warning(f"[AlphaVantage] Pas de sentiment trouvé pour {ticker}")
                return self._neutral_response(symbol, ticker)

            # Moyenne pondérée
            avg_sentiment = total_sentiment / total_relevance
            avg_relevance = total_relevance / articles_count

            # Catégoriser
            category = self.categorize_sentiment(avg_sentiment)

            result = {
                "symbol": symbol.upper(),
                "ticker": ticker,
                "sentiment_score": round(avg_sentiment, 3),
                "relevance_score": round(avg_relevance, 3),
                "category": category,
                "articles_count": articles_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": None
            }

            logger.info(f"[AlphaVantage] {symbol}: score={avg_sentiment:.2f}, category={category}, articles={articles_count}")

            # Sauvegarder en cache
            self._set_cache(symbol, result)

            return result

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("[AlphaVantage] Rate limit atteint (25 appels/jour)")
                return self._error_response(symbol, "rate_limit_exceeded")
            else:
                logger.error(f"[AlphaVantage] Erreur HTTP {e.response.status_code}: {e}")
                return self._error_response(symbol, f"http_error_{e.response.status_code}")

        except Exception as e:
            logger.error(f"[AlphaVantage] Erreur API pour {symbol}: {e}")
            return self._error_response(symbol, str(e))

    def categorize_sentiment(self, score: float) -> str:
        """
        Catégorise un score de sentiment.

        Args:
            score: Score de -1.0 à +1.0

        Returns:
            "VERY_BEARISH" | "BEARISH" | "NEUTRAL" | "BULLISH" | "VERY_BULLISH"
        """
        if score >= 0.5:
            return "VERY_BULLISH"
        elif score >= 0.2:
            return "BULLISH"
        elif score <= -0.5:
            return "VERY_BEARISH"
        elif score <= -0.2:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def _error_response(self, symbol: str, error: str) -> Dict:
        """Retourne un sentiment neutre en cas d'erreur."""
        return {
            "symbol": symbol.upper(),
            "ticker": self._resolve_ticker(symbol),
            "sentiment_score": 0.0,
            "relevance_score": 0.0,
            "category": "NEUTRAL",
            "articles_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error
        }

    def _neutral_response(self, symbol: str, ticker: str) -> Dict:
        """Retourne un sentiment neutre (pas d'erreur mais pas de données)."""
        return {
            "symbol": symbol.upper(),
            "ticker": ticker,
            "sentiment_score": 0.0,
            "relevance_score": 0.0,
            "category": "NEUTRAL",
            "articles_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": None
        }


# Fonction helper pour utilisation simple
def get_alpha_vantage_news(api_key: Optional[str] = None) -> AlphaVantageNews:
    """
    Retourne une instance AlphaVantageNews (singleton simple).

    Args:
        api_key: Clé API Alpha Vantage (ou None pour .env)

    Returns:
        Instance AlphaVantageNews
    """
    return AlphaVantageNews(api_key=api_key)


# Test rapide si exécuté directement
if __name__ == "__main__":
    print("=== Test Alpha Vantage News Sentiment ===\n")

    # Vérifier API key
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("⚠️  ALPHA_VANTAGE_API_KEY non définie dans .env")
        print("Inscrivez-vous sur https://www.alphavantage.co/ (gratuit)")
        exit(1)

    client = AlphaVantageNews(api_key=api_key)

    # Test sur quelques symboles
    test_symbols = ["BTCUSD", "EURUSD", "XAUUSD"]

    for symbol in test_symbols:
        print(f"\nTest pour {symbol}:")
        print("-" * 50)

        sentiment = client.get_news_sentiment(symbol)

        if sentiment["error"]:
            print(f"   ❌ Erreur: {sentiment['error']}")
        else:
            print(f"   ✅ Sentiment score: {sentiment['sentiment_score']:.3f}")
            print(f"   📊 Catégorie: {sentiment['category']}")
            print(f"   📰 Articles: {sentiment['articles_count']}")
            print(f"   🎯 Relevance: {sentiment['relevance_score']:.3f}")

    print("\n=== Tests terminés ===")
    print(f"\n⚠️  Rappel: Limite 25 appels/jour (cache 30 min actif)")
