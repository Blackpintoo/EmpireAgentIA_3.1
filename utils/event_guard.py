# utils/event_guard.py
"""
EVENT GUARD - Système centralisé de protection contre les annonces économiques
(PHASE 1 - Amélioration 2025-12-17)

Fonctionnalités:
1. API temps réel pour calendrier économique (Investing.com, ForexFactory, FXStreet)
2. Fenêtres de blocage dynamiques: HIGH=±30min, MEDIUM=±15min, LOW=none
3. Alertes Telegram proactives 60min avant HIGH
4. Cache intelligent pour éviter requêtes répétées
5. Fallback sur CSV local si APIs indisponibles

Objectif: Bloquer automatiquement les trades avant/après annonces importantes.
"""

from __future__ import annotations
import os
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from zoneinfo import ZoneInfo
import threading

import requests
from bs4 import BeautifulSoup

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.telegram_client import send_telegram_message
except Exception:
    def send_telegram_message(text: str, **kwargs):
        logger.info(f"[TELEGRAM_STUB] {text}")


# Fichier de persistance du calendrier live
_PERSIST_PATH = os.path.join("data", "news_calendar_live.json")

# Intervalle du thread auto-refresh (secondes) — 2 heures
_AUTO_REFRESH_INTERVAL = 7200

# Rate limit par source (secondes) — 30 minutes
_SOURCE_RATE_INTERVAL = 1800


# =============================================================================
# CONFIGURATION
# =============================================================================

class EventImpact(Enum):
    """Niveau d'impact des événements économiques"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class EconomicEvent:
    """Représentation d'un événement économique"""
    timestamp: datetime          # UTC timezone-aware
    currency: str                # USD, EUR, GBP, etc.
    impact: EventImpact
    title: str
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    source: str = "unknown"

    def _dedup_key(self) -> Tuple[str, str, str]:
        """Clé de dédupliquation: (heure tronquée, titre lowercase, currency)"""
        hour_trunc = self.timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        return (hour_trunc, self.title.lower().strip(), self.currency.upper())

    def __hash__(self):
        return hash(self._dedup_key())

    def __eq__(self, other):
        if not isinstance(other, EconomicEvent):
            return False
        return self._dedup_key() == other._dedup_key()


@dataclass
class EventGuardConfig:
    """Configuration du Event Guard"""
    # Fenêtres de blocage (minutes avant/après l'événement)
    high_window_before: int = 30
    high_window_after: int = 30
    medium_window_before: int = 15
    medium_window_after: int = 15
    low_window_before: int = 0
    low_window_after: int = 0

    # Alertes proactives
    alert_before_high_min: int = 60    # Alerte 60min avant HIGH
    alert_before_medium_min: int = 30  # Alerte 30min avant MEDIUM

    # Cache
    cache_ttl_minutes: int = 30
    cache_dir: str = "data/event_cache"

    # Sources
    enable_investing: bool = True
    enable_forexfactory: bool = True
    enable_fxstreet: bool = True
    enable_csv_fallback: bool = True
    csv_path: str = "data/news_calendar.csv"

    # Mots-clés HIGH impact (override automatique)
    high_impact_keywords: List[str] = field(default_factory=lambda: [
        "nfp", "non-farm", "fomc", "interest rate", "cpi", "inflation",
        "gdp", "powell", "lagarde", "ecb", "fed", "boe", "boj",
        "employment", "unemployment", "retail sales", "pmi"
    ])

    # Mapping symbole -> devises exposées
    symbol_currencies: Dict[str, List[str]] = field(default_factory=lambda: {
        "BTCUSD": ["USD"],
        "ETHUSD": ["USD"],
        "SOLUSD": ["USD"],
        "ADAUSD": ["USD"],
        "XAUUSD": ["USD"],
        "XAGUSD": ["USD"],
        "EURUSD": ["EUR", "USD"],
        "GBPUSD": ["GBP", "USD"],
        "USDJPY": ["USD", "JPY"],
        "AUDUSD": ["AUD", "USD"],
        "USDCAD": ["USD", "CAD"],
        "SP500": ["USD"],
        "UK100": ["GBP"],
        "USOUSD": ["USD"],
    })


# =============================================================================
# EVENT GUARD CLASS
# =============================================================================

class EventGuard:
    """
    Gardien centralisé des événements économiques.

    Vérifie si un trade peut être exécuté en fonction du calendrier économique.
    """

    def __init__(self, config: Optional[EventGuardConfig] = None):
        self.config = config or EventGuardConfig()
        self._events_cache: List[EconomicEvent] = []
        self._cache_timestamp: Optional[datetime] = None
        self._alerted_events: set = set()  # Events déjà alertés
        self._lock = threading.RLock()  # FIX 2026-03-10 R7: RLock réentrant (refresh_events → _source_rate_ok)

        # Rate limiter par source: {source_name: last_call_timestamp}
        self._source_last_fetch: Dict[str, float] = {}

        # FIX 2026-03-13 R9: Compteur d'erreurs Finnhub pour désactivation gracieuse
        self._finnhub_consecutive_errors: int = 0
        self._finnhub_max_errors: int = 3
        self._finnhub_disabled: bool = False

        # Timer auto-refresh (set par _start_auto_refresh)
        self._refresh_timer: Optional[threading.Timer] = None

        # Créer le répertoire de cache
        os.makedirs(self.config.cache_dir, exist_ok=True)

        # Charger la dernière persistance disque au démarrage
        disk_events = self._load_from_disk()
        if disk_events:
            self._events_cache = disk_events
            logger.info(f"[EVENT_GUARD] Chargé {len(disk_events)} événements depuis disque")

        # Démarrer le thread de refresh automatique
        self._start_auto_refresh()

        logger.info("[EVENT_GUARD] Initialisé avec fenêtres: "
                   f"HIGH=±{self.config.high_window_before}min, "
                   f"MEDIUM=±{self.config.medium_window_before}min, "
                   f"auto-refresh toutes les {_AUTO_REFRESH_INTERVAL // 3600}h")

    # -------------------------------------------------------------------------
    # RATE LIMITER PAR SOURCE
    # -------------------------------------------------------------------------

    def _source_rate_ok(self, source_name: str) -> bool:
        """Retourne True si la source peut être appelée (intervalle 30min respecté)."""
        with self._lock:
            now = time.time()
            last = self._source_last_fetch.get(source_name, 0.0)
            if now - last >= _SOURCE_RATE_INTERVAL:
                self._source_last_fetch[source_name] = now
                return True
            logger.debug(f"[EVENT_GUARD] Rate limit {source_name}: "
                         f"{int(now - last)}s / {_SOURCE_RATE_INTERVAL}s")
            return False

    # -------------------------------------------------------------------------
    # PERSISTANCE JSON
    # -------------------------------------------------------------------------

    def _save_to_disk(self, events: List[EconomicEvent], sources: List[str]) -> None:
        """Persiste les événements en JSON sur disque."""
        try:
            data = {
                "events": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "currency": e.currency,
                        "impact": e.impact.value,
                        "title": e.title,
                        "actual": e.actual,
                        "forecast": e.forecast,
                        "previous": e.previous,
                        "source": e.source,
                    }
                    for e in events
                ],
                "last_refresh": datetime.now(timezone.utc).isoformat(),
                "sources": sources,
            }
            os.makedirs(os.path.dirname(_PERSIST_PATH) or ".", exist_ok=True)
            with open(_PERSIST_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[EVENT_GUARD] Persisté {len(events)} événements → {_PERSIST_PATH}")
        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur persistance disque: {e}")

    def _load_from_disk(self) -> List[EconomicEvent]:
        """Charge les événements depuis le fichier JSON persisté."""
        if not os.path.exists(_PERSIST_PATH):
            return []
        try:
            with open(_PERSIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = []
            for item in data.get("events", []):
                try:
                    ts = datetime.fromisoformat(item["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    impact_str = item.get("impact", "low").lower()
                    impact = {"high": EventImpact.HIGH, "medium": EventImpact.MEDIUM,
                              "low": EventImpact.LOW}.get(impact_str, EventImpact.LOW)
                    events.append(EconomicEvent(
                        timestamp=ts,
                        currency=item.get("currency", "USD"),
                        impact=impact,
                        title=item.get("title", ""),
                        actual=item.get("actual"),
                        forecast=item.get("forecast"),
                        previous=item.get("previous"),
                        source=item.get("source", "disk"),
                    ))
                except Exception:
                    continue
            logger.debug(f"[EVENT_GUARD] Chargé {len(events)} événements depuis {_PERSIST_PATH}")
            return events
        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur lecture {_PERSIST_PATH}: {e}")
            return []

    # -------------------------------------------------------------------------
    # AUTO-REFRESH THREAD
    # -------------------------------------------------------------------------

    def _start_auto_refresh(self) -> None:
        """Démarre un timer daemon qui relance refresh_events toutes les 2h."""
        def _tick():
            try:
                self.refresh_events(force=True)
            except Exception as e:
                logger.warning(f"[EVENT_GUARD] Auto-refresh erreur: {e}")
            finally:
                self._start_auto_refresh()

        self._refresh_timer = threading.Timer(_AUTO_REFRESH_INTERVAL, _tick)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    # -------------------------------------------------------------------------
    # FINNHUB SOURCE (via econ_api)
    # -------------------------------------------------------------------------

    def _fetch_finnhub_events(self) -> List[EconomicEvent]:
        """Récupère les événements via Finnhub (délègue à econ_api._fetch_finnhub)."""
        # FIX 2026-03-13 R9: Skip Finnhub si désactivé après trop d'erreurs
        if self._finnhub_disabled:
            return []

        try:
            from utils.econ_api import _fetch_finnhub
        except ImportError:
            logger.debug("[EVENT_GUARD] econ_api._fetch_finnhub indisponible")
            return []

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=1)
            end = now + timedelta(hours=48)
            raw_events = _fetch_finnhub(start, end)

            events = []
            for ev in raw_events:
                try:
                    time_str = ev.get("time") or ev.get("datetime") or ""
                    if not time_str:
                        continue
                    ts = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    impact_str = (ev.get("impact") or "low").lower()
                    impact = {"high": EventImpact.HIGH, "medium": EventImpact.MEDIUM,
                              "low": EventImpact.LOW}.get(impact_str, EventImpact.LOW)

                    title = ev.get("event") or ev.get("title") or ""
                    # Override impact par mots-clés
                    if any(kw in title.lower() for kw in self.config.high_impact_keywords):
                        impact = EventImpact.HIGH

                    events.append(EconomicEvent(
                        timestamp=ts,
                        currency=(ev.get("currency") or "USD").upper(),
                        impact=impact,
                        title=title,
                        actual=ev.get("actual"),
                        forecast=ev.get("forecast"),
                        previous=ev.get("previous"),
                        source="finnhub",
                    ))
                except Exception:
                    continue

            logger.debug(f"[EVENT_GUARD] Finnhub: {len(events)} événements")
            self._finnhub_consecutive_errors = 0  # Reset on success
            return events

        except Exception as e:
            # FIX 2026-03-13 R9: Désactivation gracieuse après erreurs consécutives
            self._finnhub_consecutive_errors += 1
            if self._finnhub_consecutive_errors >= self._finnhub_max_errors:
                self._finnhub_disabled = True
                logger.warning(
                    f"[EVENT_GUARD] Finnhub désactivé après {self._finnhub_consecutive_errors} "
                    f"erreurs consécutives: {e}"
                )
            else:
                logger.debug(
                    f"[EVENT_GUARD] Finnhub erreur {self._finnhub_consecutive_errors}/"
                    f"{self._finnhub_max_errors}: {e}"
                )
            return []

    # -------------------------------------------------------------------------
    # FETCHERS - Sources de données
    # -------------------------------------------------------------------------

    def _fetch_investing_calendar(self) -> List[EconomicEvent]:
        """Récupère le calendrier depuis Investing.com"""
        events = []
        try:
            url = "https://www.investing.com/economic-calendar/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }

            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.debug(f"[EVENT_GUARD] Investing.com status {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, 'html.parser')

            # Parser les événements du tableau
            rows = soup.select('tr.js-event-item')
            today = datetime.now(timezone.utc).date()

            for row in rows[:50]:  # Limiter aux 50 premiers
                try:
                    # Date/Heure
                    time_cell = row.select_one('td.time')
                    if not time_cell:
                        continue
                    time_str = time_cell.get_text(strip=True)

                    # Currency
                    currency_cell = row.select_one('td.flagCur')
                    currency = currency_cell.get_text(strip=True) if currency_cell else "USD"

                    # Impact (nombre de bulls)
                    impact_cell = row.select_one('td.sentiment')
                    bulls = len(impact_cell.select('i.grayFullBullishIcon')) if impact_cell else 0
                    if bulls >= 3:
                        impact = EventImpact.HIGH
                    elif bulls == 2:
                        impact = EventImpact.MEDIUM
                    else:
                        impact = EventImpact.LOW

                    # Title
                    title_cell = row.select_one('td.event')
                    title = title_cell.get_text(strip=True) if title_cell else "Unknown"

                    # Override impact par mots-clés
                    title_lower = title.lower()
                    if any(kw in title_lower for kw in self.config.high_impact_keywords):
                        impact = EventImpact.HIGH

                    # Parser l'heure
                    try:
                        if ":" in time_str:
                            hour, minute = map(int, time_str.split(":"))
                            event_dt = datetime(today.year, today.month, today.day,
                                              hour, minute, tzinfo=timezone.utc)
                        else:
                            continue
                    except ValueError:
                        continue

                    events.append(EconomicEvent(
                        timestamp=event_dt,
                        currency=currency.upper(),
                        impact=impact,
                        title=title,
                        source="investing"
                    ))

                except Exception as e:
                    logger.debug(f"[EVENT_GUARD] Erreur parsing row Investing: {e}")
                    continue

            logger.debug(f"[EVENT_GUARD] Investing.com: {len(events)} événements")

        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur fetch Investing.com: {e}")

        return events

    def _fetch_forexfactory_calendar(self) -> List[EconomicEvent]:
        """Récupère le calendrier depuis ForexFactory"""
        events = []
        try:
            url = "https://www.forexfactory.com/calendar"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }

            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return events

            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.select('tr.calendar__row')

            current_date = datetime.now(timezone.utc).date()

            for row in rows[:50]:
                try:
                    # Impact
                    impact_cell = row.select_one('td.calendar__impact span')
                    if not impact_cell:
                        continue

                    impact_class = impact_cell.get('class', [])
                    if any('high' in c for c in impact_class):
                        impact = EventImpact.HIGH
                    elif any('medium' in c for c in impact_class):
                        impact = EventImpact.MEDIUM
                    else:
                        impact = EventImpact.LOW

                    # Currency
                    currency_cell = row.select_one('td.calendar__currency')
                    currency = currency_cell.get_text(strip=True) if currency_cell else "USD"

                    # Title
                    title_cell = row.select_one('td.calendar__event span')
                    title = title_cell.get_text(strip=True) if title_cell else "Unknown"

                    # Time
                    time_cell = row.select_one('td.calendar__time')
                    time_str = time_cell.get_text(strip=True) if time_cell else ""

                    # Override impact
                    title_lower = title.lower()
                    if any(kw in title_lower for kw in self.config.high_impact_keywords):
                        impact = EventImpact.HIGH

                    # Parser l'heure
                    try:
                        if ":" in time_str and "am" in time_str.lower() or "pm" in time_str.lower():
                            # Format 12h
                            time_clean = time_str.lower().replace("am", "").replace("pm", "").strip()
                            hour, minute = map(int, time_clean.split(":"))
                            if "pm" in time_str.lower() and hour < 12:
                                hour += 12
                            event_dt = datetime(current_date.year, current_date.month,
                                              current_date.day, hour, minute, tzinfo=timezone.utc)
                        elif ":" in time_str:
                            hour, minute = map(int, time_str.split(":"))
                            event_dt = datetime(current_date.year, current_date.month,
                                              current_date.day, hour, minute, tzinfo=timezone.utc)
                        else:
                            continue
                    except ValueError:
                        continue

                    events.append(EconomicEvent(
                        timestamp=event_dt,
                        currency=currency.upper(),
                        impact=impact,
                        title=title,
                        source="forexfactory"
                    ))

                except Exception as e:
                    logger.debug(f"[EVENT_GUARD] Erreur parsing row FF: {e}")
                    continue

            logger.debug(f"[EVENT_GUARD] ForexFactory: {len(events)} événements")

        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur fetch ForexFactory: {e}")

        return events

    def _fetch_fxstreet_calendar(self) -> List[EconomicEvent]:
        """Récupère le calendrier depuis FXStreet API"""
        events = []
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            url = f"https://calendar-api.fxstreet.com/en/api/v1/eventDates/{today}/{today}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            }

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return events

            data = response.json()

            for item in data[:50]:
                try:
                    # Impact
                    volatility = item.get("volatility", "").lower()
                    if volatility == "high":
                        impact = EventImpact.HIGH
                    elif volatility == "medium":
                        impact = EventImpact.MEDIUM
                    else:
                        impact = EventImpact.LOW

                    # Currency
                    currency = item.get("currencyCode", "USD").upper()

                    # Title
                    title = item.get("name", "Unknown")

                    # Override impact
                    title_lower = title.lower()
                    if any(kw in title_lower for kw in self.config.high_impact_keywords):
                        impact = EventImpact.HIGH

                    # Timestamp
                    date_str = item.get("dateUtc", "")
                    if date_str:
                        event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    else:
                        continue

                    events.append(EconomicEvent(
                        timestamp=event_dt,
                        currency=currency,
                        impact=impact,
                        title=title,
                        actual=item.get("actual"),
                        forecast=item.get("consensus"),
                        previous=item.get("previous"),
                        source="fxstreet"
                    ))

                except Exception as e:
                    logger.debug(f"[EVENT_GUARD] Erreur parsing FXStreet: {e}")
                    continue

            logger.debug(f"[EVENT_GUARD] FXStreet: {len(events)} événements")

        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur fetch FXStreet: {e}")

        return events

    def _load_csv_calendar(self) -> List[EconomicEvent]:
        """Charge le calendrier depuis le CSV local (fallback)"""
        events = []
        csv_path = self.config.csv_path

        if not os.path.exists(csv_path):
            return events

        try:
            import csv
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        dt_str = row.get("datetime", "").strip()
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                        dt = dt.replace(tzinfo=ZoneInfo("Europe/Zurich")).astimezone(timezone.utc)

                        currency = row.get("currency", "USD").upper().strip()
                        impact_str = row.get("impact", "low").lower().strip()

                        if impact_str == "high":
                            impact = EventImpact.HIGH
                        elif impact_str == "medium":
                            impact = EventImpact.MEDIUM
                        else:
                            impact = EventImpact.LOW

                        title = row.get("title", "").strip()

                        events.append(EconomicEvent(
                            timestamp=dt,
                            currency=currency,
                            impact=impact,
                            title=title,
                            source="csv"
                        ))

                    except Exception:
                        continue

            logger.debug(f"[EVENT_GUARD] CSV: {len(events)} événements")

        except Exception as e:
            logger.warning(f"[EVENT_GUARD] Erreur lecture CSV: {e}")

        return events

    # -------------------------------------------------------------------------
    # CACHE & REFRESH
    # -------------------------------------------------------------------------

    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache est encore valide"""
        if not self._cache_timestamp:
            return False

        age = datetime.now(timezone.utc) - self._cache_timestamp
        return age.total_seconds() < self.config.cache_ttl_minutes * 60

    def refresh_events(self, force: bool = False) -> List[EconomicEvent]:
        """Rafraîchit la liste des événements depuis toutes les sources.

        Ordre: FXStreet → Finnhub → Investing.com, chacune respectant le rate limiter.
        Fallback disque si aucun résultat API.
        """
        with self._lock:
            if not force and self._is_cache_valid():
                return self._events_cache

            all_events: List[EconomicEvent] = []
            sources_used: List[str] = []

            # 1) FXStreet (API JSON, source principale)
            if self.config.enable_fxstreet and self._source_rate_ok("fxstreet"):
                fxs = self._fetch_fxstreet_calendar()
                if fxs:
                    all_events.extend(fxs)
                    sources_used.append("fxstreet")

            # 2) Finnhub (via econ_api)
            if self._source_rate_ok("finnhub"):
                fh = self._fetch_finnhub_events()
                if fh:
                    all_events.extend(fh)
                    sources_used.append("finnhub")

            # 3) Investing.com (scraping)
            if self.config.enable_investing and self._source_rate_ok("investing"):
                inv = self._fetch_investing_calendar()
                if inv:
                    all_events.extend(inv)
                    sources_used.append("investing")

            # 4) Fallback CSV si pas assez d'événements
            if len(all_events) < 5 and self.config.enable_csv_fallback:
                csv_ev = self._load_csv_calendar()
                if csv_ev:
                    all_events.extend(csv_ev)
                    sources_used.append("csv")

            # 5) Fallback disque si aucun résultat API
            if not all_events:
                disk_events = self._load_from_disk()
                if disk_events:
                    all_events = disk_events
                    sources_used.append("disk_fallback")
                    logger.info(f"[EVENT_GUARD] Fallback disque: {len(disk_events)} événements")

            # 6) Dédupliquation renforcée (via __hash__/__eq__ basés sur _dedup_key)
            seen: Dict[Tuple[str, str, str], EconomicEvent] = {}
            for ev in all_events:
                key = ev._dedup_key()
                if key not in seen:
                    seen[key] = ev

            unique_events = sorted(seen.values(), key=lambda e: e.timestamp)

            # 7) Persister si on a des événements
            if unique_events and sources_used and "disk_fallback" not in sources_used:
                self._save_to_disk(unique_events, sources_used)

            self._events_cache = unique_events
            self._cache_timestamp = datetime.now(timezone.utc)

            logger.info(f"[EVENT_GUARD] Calendrier rafraîchi: {len(unique_events)} événements "
                       f"(HIGH: {sum(1 for e in unique_events if e.impact == EventImpact.HIGH)}, "
                       f"MEDIUM: {sum(1 for e in unique_events if e.impact == EventImpact.MEDIUM)}) "
                       f"sources={sources_used}")

            return unique_events

    # -------------------------------------------------------------------------
    # CORE LOGIC
    # -------------------------------------------------------------------------

    def get_blocking_window(self, impact: EventImpact) -> Tuple[int, int]:
        """Retourne la fenêtre de blocage (before, after) en minutes pour un impact"""
        if impact == EventImpact.HIGH:
            return self.config.high_window_before, self.config.high_window_after
        elif impact == EventImpact.MEDIUM:
            return self.config.medium_window_before, self.config.medium_window_after
        else:
            return self.config.low_window_before, self.config.low_window_after

    def get_currencies_for_symbol(self, symbol: str) -> List[str]:
        """Retourne les devises exposées pour un symbole"""
        symbol = symbol.upper()

        # Chercher dans la config
        if symbol in self.config.symbol_currencies:
            return self.config.symbol_currencies[symbol]

        # Déduire des 6 premiers caractères
        if len(symbol) >= 6:
            base = symbol[:3]
            quote = symbol[3:6]
            return [base, quote]

        return ["USD"]

    def get_upcoming_events(
        self,
        symbol: str,
        hours_ahead: int = 24
    ) -> List[EconomicEvent]:
        """Récupère les événements à venir pour un symbole"""
        self.refresh_events()

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        currencies = set(self.get_currencies_for_symbol(symbol))

        upcoming = []
        for event in self._events_cache:
            if event.currency in currencies:
                if now <= event.timestamp <= cutoff:
                    upcoming.append(event)

        return upcoming

    def is_blocked(
        self,
        symbol: str,
        now: Optional[datetime] = None
    ) -> Tuple[bool, Optional[EconomicEvent], str]:
        """
        Vérifie si le trading est bloqué pour un symbole.

        Returns:
            Tuple[is_blocked, blocking_event, reason]
        """
        self.refresh_events()

        if now is None:
            now = datetime.now(timezone.utc)

        currencies = set(self.get_currencies_for_symbol(symbol))

        for event in self._events_cache:
            if event.currency not in currencies:
                continue

            # Ignorer les événements LOW
            if event.impact == EventImpact.LOW or event.impact == EventImpact.NONE:
                continue

            before_min, after_min = self.get_blocking_window(event.impact)

            # Calculer la fenêtre
            window_start = event.timestamp - timedelta(minutes=before_min)
            window_end = event.timestamp + timedelta(minutes=after_min)

            if window_start <= now <= window_end:
                reason = (f"{event.impact.value.upper()} impact: {event.title} "
                         f"({event.currency}) @ {event.timestamp.strftime('%H:%M UTC')}")
                return True, event, reason

        return False, None, ""

    def check_and_alert(self, symbol: str) -> None:
        """Vérifie et envoie des alertes proactives pour les événements à venir"""
        self.refresh_events()

        now = datetime.now(timezone.utc)
        currencies = set(self.get_currencies_for_symbol(symbol))

        for event in self._events_cache:
            if event.currency not in currencies:
                continue

            # Calculer le temps avant l'événement
            time_until = (event.timestamp - now).total_seconds() / 60  # minutes

            # Event ID pour éviter alertes répétées
            event_id = f"{event.timestamp.isoformat()}_{event.currency}_{event.title}"

            if event_id in self._alerted_events:
                continue

            # Alerte pour HIGH
            if (event.impact == EventImpact.HIGH and
                0 < time_until <= self.config.alert_before_high_min):

                msg = (f"⚠️ ALERTE EVENT HIGH dans {int(time_until)}min\n"
                      f"📊 {event.title}\n"
                      f"💱 {event.currency}\n"
                      f"🕐 {event.timestamp.strftime('%H:%M UTC')}\n"
                      f"🚫 Trading {symbol} bloqué ±{self.config.high_window_before}min")

                try:
                    send_telegram_message(text=msg, kind="alert")
                    self._alerted_events.add(event_id)
                    logger.info(f"[EVENT_GUARD] Alerte envoyée: {event.title}")
                except Exception as e:
                    logger.warning(f"[EVENT_GUARD] Erreur envoi alerte: {e}")

            # Alerte pour MEDIUM
            elif (event.impact == EventImpact.MEDIUM and
                  0 < time_until <= self.config.alert_before_medium_min):

                msg = (f"📢 Event MEDIUM dans {int(time_until)}min\n"
                      f"📊 {event.title}\n"
                      f"💱 {event.currency}")

                try:
                    send_telegram_message(text=msg, kind="status")
                    self._alerted_events.add(event_id)
                except Exception:
                    pass

    def should_allow_trade(
        self,
        symbol: str,
        direction: str
    ) -> Tuple[bool, str, Optional[EconomicEvent]]:
        """
        Interface principale pour l'orchestrateur.

        Returns:
            Tuple[allowed, reason, blocking_event]
        """
        # Vérifier le blocage
        is_blocked, event, reason = self.is_blocked(symbol)

        if is_blocked:
            return False, f"EVENT_BLOCK: {reason}", event

        # Envoyer alertes proactives
        self.check_and_alert(symbol)

        return True, "no_event_conflict", None

    def get_status(self, symbol: str) -> Dict[str, Any]:
        """Retourne le statut complet pour un symbole"""
        is_blocked, event, reason = self.is_blocked(symbol)
        upcoming = self.get_upcoming_events(symbol, hours_ahead=12)

        return {
            "symbol": symbol,
            "is_blocked": is_blocked,
            "blocking_reason": reason,
            "blocking_event": {
                "title": event.title,
                "currency": event.currency,
                "impact": event.impact.value,
                "timestamp": event.timestamp.isoformat()
            } if event else None,
            "upcoming_events": [
                {
                    "title": e.title,
                    "currency": e.currency,
                    "impact": e.impact.value,
                    "timestamp": e.timestamp.isoformat(),
                    "minutes_until": int((e.timestamp - datetime.now(timezone.utc)).total_seconds() / 60)
                }
                for e in upcoming[:10]
            ],
            "cache_age_seconds": int((datetime.now(timezone.utc) - self._cache_timestamp).total_seconds())
                                if self._cache_timestamp else None,
            "total_events_cached": len(self._events_cache)
        }


# =============================================================================
# INSTANCE GLOBALE
# =============================================================================

_event_guard: Optional[EventGuard] = None


def get_event_guard(config: Optional[EventGuardConfig] = None) -> EventGuard:
    """Récupère ou crée l'instance globale de EventGuard"""
    global _event_guard

    if _event_guard is None:
        _event_guard = EventGuard(config)

    return _event_guard


def is_trade_blocked_by_event(symbol: str) -> Tuple[bool, str]:
    """
    Fonction utilitaire rapide pour vérifier si un trade est bloqué.

    Returns:
        Tuple[is_blocked, reason]
    """
    guard = get_event_guard()
    allowed, reason, _ = guard.should_allow_trade(symbol, "")
    return not allowed, reason


def get_upcoming_high_events(symbol: str, hours: int = 6) -> List[Dict[str, Any]]:
    """Récupère les événements HIGH à venir pour un symbole"""
    guard = get_event_guard()
    events = guard.get_upcoming_events(symbol, hours)

    return [
        {
            "title": e.title,
            "currency": e.currency,
            "timestamp": e.timestamp.isoformat(),
            "minutes_until": int((e.timestamp - datetime.now(timezone.utc)).total_seconds() / 60)
        }
        for e in events
        if e.impact == EventImpact.HIGH
    ]
