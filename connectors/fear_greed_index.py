"""
Fear & Greed Index API Integration (Crypto Market Sentiment)

API GRATUITE sans authentification
Documentation : https://alternative.me/crypto/fear-and-greed-index/

Fonctionnalités :
- Récupération du Fear & Greed Index crypto (0-100)
- Catégorisation : Extreme Fear, Fear, Neutral, Greed, Extreme Greed
- Cache local (1h TTL)
- Pas de rate limit (API publique)
"""

import json
import time
import requests
from datetime import datetime, timezone
from typing import Dict, Optional
from pathlib import Path

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class FearGreedIndex:
    """
    Client pour l'API Fear & Greed Index (alternative.me).

    Aucune configuration requise (API gratuite sans clé).

    Configuration optionnelle dans config.yaml :
        external_apis:
          fear_greed:
            enabled: true
            cache_ttl: 3600
    """

    BASE_URL = "https://api.alternative.me/fng/"
    CACHE_DIR = "data/cache"
    CACHE_FILE = "fear_greed_index_cache.json"
    DEFAULT_CACHE_TTL = 3600  # 1 heure

    # Seuils de catégorisation
    CATEGORIES = {
        "EXTREME_FEAR": (0, 25),
        "FEAR": (26, 45),
        "NEUTRAL": (46, 55),
        "GREED": (56, 75),
        "EXTREME_GREED": (76, 100),
    }

    def __init__(self, cache_ttl: Optional[int] = None):
        """
        Initialise le client Fear & Greed Index.

        Args:
            cache_ttl: Durée du cache en secondes (défaut: 3600 = 1h)
        """
        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.cache_path = Path(self.CACHE_DIR) / self.CACHE_FILE
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"[FearGreed] Initialisé avec cache TTL={self.cache_ttl}s")

    def _get_cache(self) -> Optional[Dict]:
        """Charge le cache local s'il existe et est valide."""
        if not self.cache_path.exists():
            return None

        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            cache_time = cache_data.get("timestamp", 0)
            now = time.time()

            if now - cache_time < self.cache_ttl:
                logger.debug(f"[FearGreed] Cache HIT (age={int(now - cache_time)}s)")
                return cache_data.get("index", {})
            else:
                logger.debug(f"[FearGreed] Cache EXPIRED (age={int(now - cache_time)}s)")
                return None
        except Exception as e:
            logger.warning(f"[FearGreed] Erreur lecture cache: {e}")
            return None

    def _set_cache(self, index_data: Dict) -> None:
        """Sauvegarde l'index dans le cache local."""
        try:
            cache_data = {
                "timestamp": time.time(),
                "index": index_data
            }
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"[FearGreed] Cache sauvegardé")
        except Exception as e:
            logger.warning(f"[FearGreed] Erreur écriture cache: {e}")

    def get_fear_greed_index(self, use_cache: bool = True) -> Dict:
        """
        Récupère l'indice Fear & Greed actuel.

        Args:
            use_cache: Utiliser le cache local si disponible

        Returns:
            Dict: {
                "value": 42,                    # 0-100
                "value_classification": "Fear", # Extreme Fear|Fear|Neutral|Greed|Extreme Greed
                "category": "FEAR",             # EXTREME_FEAR|FEAR|NEUTRAL|GREED|EXTREME_GREED
                "timestamp": "2025-11-29T12:34:56Z",
                "time_until_update": "14 hours", # Temps avant prochaine mise à jour
                "error": None
            }
        """
        # Vérifier cache
        if use_cache:
            cached = self._get_cache()
            if cached is not None:
                return cached

        # Appel API (pas de paramètres requis - limite=1 pour avoir le dernier)
        params = {"limit": 1}

        try:
            logger.info(f"[FearGreed] Appel API")
            response = requests.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Parser réponse
            if "data" not in data or not data["data"]:
                logger.error(f"[FearGreed] Réponse API invalide: {data}")
                return self._error_response("invalid_response")

            latest = data["data"][0]

            value = int(latest.get("value", 50))
            value_classification = latest.get("value_classification", "Neutral")
            timestamp_unix = int(latest.get("timestamp", 0))
            time_until_update = latest.get("time_until_update", "unknown")

            # Catégoriser selon nos seuils
            category = self.categorize_value(value)

            result = {
                "value": value,
                "value_classification": value_classification,  # Texte de l'API
                "category": category,  # Notre catégorie
                "timestamp": datetime.fromtimestamp(timestamp_unix, tz=timezone.utc).isoformat(),
                "time_until_update": time_until_update,
                "error": None
            }

            logger.info(f"[FearGreed] Index={value} ({category}), next_update={time_until_update}")

            # Sauvegarder en cache
            self._set_cache(result)

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"[FearGreed] Erreur réseau: {e}")
            return self._error_response(f"network_error: {e}")

        except Exception as e:
            logger.error(f"[FearGreed] Erreur API: {e}")
            return self._error_response(str(e))

    def categorize_value(self, value: int) -> str:
        """
        Catégorise une valeur Fear & Greed.

        Args:
            value: Valeur 0-100

        Returns:
            "EXTREME_FEAR" | "FEAR" | "NEUTRAL" | "GREED" | "EXTREME_GREED"
        """
        for category, (min_val, max_val) in self.CATEGORIES.items():
            if min_val <= value <= max_val:
                return category

        return "NEUTRAL"  # Fallback

    def get_sentiment_signal(self, value: Optional[int] = None) -> str:
        """
        Convertit l'index en signal de trading.

        Args:
            value: Valeur 0-100 (ou None pour récupérer l'index actuel)

        Returns:
            "CONTRARIAN_BUY" | "NEUTRAL" | "CONTRARIAN_SELL"

        Logique contrarian :
        - Extreme Fear (0-25) → Opportunité d'achat (panic selling)
        - Fear (26-45) → Léger bias achat
        - Neutral (46-55) → Pas de signal
        - Greed (56-75) → Léger bias vente
        - Extreme Greed (76-100) → Opportunité de vente (euphoria)
        """
        if value is None:
            index_data = self.get_fear_greed_index()
            if index_data["error"]:
                return "NEUTRAL"
            value = index_data["value"]

        if value <= 25:
            return "CONTRARIAN_BUY"  # Extreme Fear = buy opportunity
        elif value <= 45:
            return "NEUTRAL"  # Fear = légèrement positif mais pas assez
        elif value <= 55:
            return "NEUTRAL"  # Neutral
        elif value <= 75:
            return "NEUTRAL"  # Greed = légèrement négatif mais pas assez
        else:
            return "CONTRARIAN_SELL"  # Extreme Greed = sell opportunity

    def _error_response(self, error: str) -> Dict:
        """Retourne un index neutre en cas d'erreur."""
        return {
            "value": 50,
            "value_classification": "Neutral",
            "category": "NEUTRAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_until_update": "unknown",
            "error": error
        }


# Fonction helper pour utilisation simple
def get_fear_greed_index() -> FearGreedIndex:
    """
    Retourne une instance FearGreedIndex (singleton simple).

    Returns:
        Instance FearGreedIndex
    """
    return FearGreedIndex()


# Test rapide si exécuté directement
if __name__ == "__main__":
    print("=== Test Fear & Greed Index ===\n")

    client = FearGreedIndex()

    # Test 1 : Récupérer l'index actuel
    print("1. Récupération de l'index actuel...")
    index_data = client.get_fear_greed_index()

    if index_data["error"]:
        print(f"   ❌ Erreur: {index_data['error']}")
    else:
        print(f"   ✅ Valeur: {index_data['value']}/100")
        print(f"   📊 Catégorie: {index_data['category']}")
        print(f"   📝 Classification: {index_data['value_classification']}")
        print(f"   🕒 Prochaine MAJ: {index_data['time_until_update']}")

    # Test 2 : Signal de trading contrarian
    print("\n2. Signal de trading contrarian...")
    signal = client.get_sentiment_signal()
    print(f"   🎯 Signal: {signal}")

    # Test 3 : Catégorisation manuelle
    print("\n3. Tests de catégorisation...")
    test_values = [10, 30, 50, 70, 90]
    for val in test_values:
        category = client.categorize_value(val)
        signal = client.get_sentiment_signal(val)
        print(f"   {val:3d} → {category:15s} → {signal}")

    # Test 4 : Vérifier le cache
    print("\n4. Test du cache...")
    print("   Appel #1 (API)...")
    start = time.time()
    client.get_fear_greed_index(use_cache=False)
    api_time = time.time() - start

    print("   Appel #2 (Cache)...")
    start = time.time()
    client.get_fear_greed_index(use_cache=True)
    cache_time = time.time() - start

    print(f"   ✅ API: {api_time*1000:.0f}ms, Cache: {cache_time*1000:.0f}ms ({cache_time/api_time*100:.0f}% plus rapide)")

    print("\n=== Tests terminés ===")
    print("\n💡 Note: API gratuite, pas de limite de taux (mise à jour toutes les 8h)")
