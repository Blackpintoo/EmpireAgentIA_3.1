"""
Finnhub Economic Calendar API Integration

API gratuite : 60 appels/minute
Documentation : https://finnhub.io/docs/api/economic-calendar

Fonctionnalités :
- Récupération événements économiques
- Filtrage HIGH impact seulement
- Vérification freeze periods (±15 min autour événements)
- Cache local (1h TTL) pour économiser les appels API
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class FinnhubCalendar:
    """
    Client Finnhub pour le calendrier économique.

    Configuration requise dans .env :
        FINNHUB_API_KEY=your_api_key_here

    Ou dans config.yaml :
        external_apis:
          finnhub:
            enabled: true
            api_key: "your_api_key"
            cache_ttl: 3600
    """

    BASE_URL = "https://finnhub.io/api/v1"
    CACHE_DIR = "data/cache"
    CACHE_FILE = "finnhub_calendar_cache.json"
    DEFAULT_CACHE_TTL = 3600  # 1 heure

    # Événements à haute importance
    HIGH_IMPACT_EVENTS = [
        "FOMC",           # Federal Open Market Committee
        "NFP",            # Non-Farm Payrolls
        "CPI",            # Consumer Price Index
        "GDP",            # Gross Domestic Product
        "ECB",            # European Central Bank
        "BOE",            # Bank of England
        "BOJ",            # Bank of Japan
        "UNEMPLOYMENT",   # Taux de chômage
        "RETAIL SALES",   # Ventes au détail
        "INTEREST RATE",  # Décisions taux d'intérêt
    ]

    def __init__(self, api_key: Optional[str] = None, cache_ttl: Optional[int] = None):
        """
        Initialise le client Finnhub.

        Args:
            api_key: Clé API Finnhub (ou None pour charger depuis .env)
            cache_ttl: Durée du cache en secondes (défaut: 3600)
        """
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        if not self.api_key:
            logger.warning("[Finnhub] API key manquante. Définir FINNHUB_API_KEY dans .env")

        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.cache_path = Path(self.CACHE_DIR) / self.CACHE_FILE
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"[Finnhub] Initialisé avec cache TTL={self.cache_ttl}s")

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
                logger.debug(f"[Finnhub] Cache HIT (age={int(now - cache_time)}s)")
                return cache_data.get("events", [])
            else:
                logger.debug(f"[Finnhub] Cache EXPIRED (age={int(now - cache_time)}s)")
                return None
        except Exception as e:
            logger.warning(f"[Finnhub] Erreur lecture cache: {e}")
            return None

    def _set_cache(self, events: List[Dict]) -> None:
        """Sauvegarde les événements dans le cache local."""
        try:
            cache_data = {
                "timestamp": time.time(),
                "events": events
            }
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"[Finnhub] Cache sauvegardé ({len(events)} événements)")
        except Exception as e:
            logger.warning(f"[Finnhub] Erreur écriture cache: {e}")

    def get_economic_events(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Récupère les événements économiques depuis Finnhub.

        Args:
            date_from: Date début (format YYYY-MM-DD), défaut: aujourd'hui
            date_to: Date fin (format YYYY-MM-DD), défaut: aujourd'hui + 7 jours
            use_cache: Utiliser le cache local si disponible

        Returns:
            Liste d'événements : [
                {
                    "event": "FOMC Meeting",
                    "date": "2025-11-29",
                    "time": "14:00:00",
                    "country": "US",
                    "actual": "",
                    "estimate": "",
                    "previous": "",
                    "impact": "high"
                },
                ...
            ]
        """
        # Vérifier cache
        if use_cache:
            cached = self._get_cache()
            if cached is not None:
                return cached

        # Vérifier API key
        if not self.api_key:
            logger.error("[Finnhub] API key manquante, impossible de récupérer les événements")
            return []

        # Dates par défaut
        if date_from is None:
            date_from = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if date_to is None:
            date_to = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

        # Appel API
        url = f"{self.BASE_URL}/calendar/economic"
        params = {
            "from": date_from,
            "to": date_to,
            "token": self.api_key
        }

        try:
            logger.info(f"[Finnhub] Appel API : {date_from} -> {date_to}")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            events = data.get("economicCalendar", [])

            logger.info(f"[Finnhub] {len(events)} événements récupérés")

            # Sauvegarder en cache
            self._set_cache(events)

            return events

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("[Finnhub] Rate limit atteint (60 appels/min)")
            else:
                logger.error(f"[Finnhub] Erreur HTTP {e.response.status_code}: {e}")
            return []

        except Exception as e:
            logger.error(f"[Finnhub] Erreur API: {e}")
            return []

    def filter_high_impact_events(self, events: List[Dict]) -> List[Dict]:
        """
        Filtre uniquement les événements à haute importance.

        Args:
            events: Liste complète des événements

        Returns:
            Liste filtrée (HIGH impact seulement)
        """
        high_impact = []

        for event in events:
            event_name = str(event.get("event", "")).upper()
            impact = str(event.get("impact", "")).upper()

            # Méthode 1 : Champ "impact" = "high"
            if impact == "HIGH":
                high_impact.append(event)
                continue

            # Méthode 2 : Nom contient un mot-clé HIGH_IMPACT
            if any(keyword in event_name for keyword in self.HIGH_IMPACT_EVENTS):
                high_impact.append(event)

        logger.debug(f"[Finnhub] {len(high_impact)}/{len(events)} événements HIGH impact")
        return high_impact

    def is_news_freeze_period(
        self,
        symbol: str,
        timestamp: Optional[datetime] = None,
        freeze_minutes: int = 15
    ) -> Tuple[bool, Optional[str]]:
        """
        Vérifie si on est dans une période de freeze autour d'un événement HIGH.

        Args:
            symbol: Symbole tradé (ex: "EURUSD", "BTCUSD")
            timestamp: Datetime à vérifier (défaut: maintenant)
            freeze_minutes: Minutes avant/après événement (défaut: 15)

        Returns:
            (is_freeze, event_name)
            - (True, "FOMC Meeting") si freeze actif
            - (False, None) si pas de freeze
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Récupérer événements du jour
        date_str = timestamp.strftime("%Y-%m-%d")
        events = self.get_economic_events(date_from=date_str, date_to=date_str)

        # Filtrer HIGH impact
        high_events = self.filter_high_impact_events(events)

        # Mapping symbole -> pays concernés
        symbol_countries = {
            "EURUSD": ["US", "EU", "EUR"],
            "GBPUSD": ["US", "GB", "UK"],
            "USDJPY": ["US", "JP"],
            "AUDUSD": ["US", "AU"],
            "XAUUSD": ["US"],  # Or très sensible USD
            "BTCUSD": ["US"],  # Crypto sensible USD
            "ETHUSD": ["US"],
            "LTCUSD": ["US"],  # Litecoin
            "DJ30": ["US"],
            "NAS100": ["US"],
            "GER40": ["DE", "EU", "EUR"],
            "CL-OIL": ["US"],  # Pétrole WTI
        }

        countries = symbol_countries.get(symbol.upper(), ["US"])  # Défaut: US

        # Vérifier chaque événement
        for event in high_events:
            event_country = str(event.get("country", "")).upper()

            # Ignorer si pays non concerné
            if event_country not in countries:
                continue

            # Parser datetime événement
            event_date = event.get("date", "")  # "2025-11-29"
            event_time = event.get("time", "00:00:00")  # "14:00:00"

            try:
                event_datetime_str = f"{event_date} {event_time}"
                event_datetime = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M:%S")
                event_datetime = event_datetime.replace(tzinfo=timezone.utc)
            except Exception as e:
                logger.warning(f"[Finnhub] Impossible de parser datetime: {e}")
                continue

            # Calculer différence
            delta = abs((timestamp - event_datetime).total_seconds() / 60)  # minutes

            if delta <= freeze_minutes:
                event_name = event.get("event", "Unknown Event")
                logger.warning(f"[Finnhub] FREEZE actif pour {symbol}: {event_name} dans {int(delta)} min")
                return True, event_name

        return False, None

    def get_next_high_impact_event(self, days_ahead: int = 7) -> Optional[Dict]:
        """
        Récupère le prochain événement HIGH impact dans les N jours à venir.

        Args:
            days_ahead: Nombre de jours à regarder (défaut: 7)

        Returns:
            Dict de l'événement ou None
        """
        date_from = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_to = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        events = self.get_economic_events(date_from=date_from, date_to=date_to)
        high_events = self.filter_high_impact_events(events)

        if not high_events:
            return None

        # Trier par date/heure
        now = datetime.now(timezone.utc)
        future_events = []

        for event in high_events:
            try:
                event_date = event.get("date", "")
                event_time = event.get("time", "00:00:00")
                event_datetime_str = f"{event_date} {event_time}"
                event_datetime = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M:%S")
                event_datetime = event_datetime.replace(tzinfo=timezone.utc)

                if event_datetime > now:
                    event["_datetime"] = event_datetime
                    future_events.append(event)
            except:
                continue

        if not future_events:
            return None

        # Trier et retourner le plus proche
        future_events.sort(key=lambda e: e["_datetime"])
        return future_events[0]


# Fonction helper pour utilisation simple
def get_finnhub_calendar(api_key: Optional[str] = None) -> FinnhubCalendar:
    """
    Retourne une instance FinnhubCalendar (singleton simple).

    Args:
        api_key: Clé API Finnhub (ou None pour .env)

    Returns:
        Instance FinnhubCalendar
    """
    return FinnhubCalendar(api_key=api_key)


# Test rapide si exécuté directement
if __name__ == "__main__":
    print("=== Test Finnhub Calendar ===\n")

    # Vérifier API key
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("⚠️  FINNHUB_API_KEY non définie dans .env")
        print("Inscrivez-vous sur https://finnhub.io/ (gratuit)")
        exit(1)

    client = FinnhubCalendar(api_key=api_key)

    # Test 1 : Récupérer événements
    print("1. Récupération événements économiques...")
    events = client.get_economic_events()
    print(f"   ✅ {len(events)} événements récupérés\n")

    # Test 2 : Filtrer HIGH impact
    print("2. Filtrage HIGH impact...")
    high_events = client.filter_high_impact_events(events)
    print(f"   ✅ {len(high_events)} événements HIGH impact\n")

    if high_events:
        print("   Exemples:")
        for event in high_events[:3]:
            print(f"   - {event.get('event')} ({event.get('country')}) le {event.get('date')} à {event.get('time')}")

    # Test 3 : Vérifier freeze period
    print("\n3. Vérification freeze period pour EURUSD...")
    is_freeze, event_name = client.is_news_freeze_period("EURUSD")
    if is_freeze:
        print(f"   ⚠️  FREEZE actif: {event_name}")
    else:
        print(f"   ✅ Pas de freeze actuellement")

    # Test 4 : Prochain événement
    print("\n4. Prochain événement HIGH impact...")
    next_event = client.get_next_high_impact_event()
    if next_event:
        print(f"   ✅ {next_event.get('event')} ({next_event.get('country')})")
        print(f"      Date: {next_event.get('date')} {next_event.get('time')}")
    else:
        print("   ℹ️  Aucun événement HIGH dans les 7 prochains jours")

    print("\n=== Tests terminés ===")
