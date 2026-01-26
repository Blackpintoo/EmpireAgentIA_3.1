#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECONOMIC CALENDAR - Gestion amelioree des evenements economiques
PHASE 2 - 2025-12-25

Fonctionnalites:
1. Integration avec plusieurs sources de calendrier economique
2. Filtrage par impact (HIGH/MEDIUM/LOW)
3. Buffer configurable avant/apres les annonces
4. Cache intelligent pour eviter les appels API excessifs
5. Mapping symboles -> devises impactees

Sources supportees:
- FXStreet Calendar API (gratuit, limite)
- Forex Factory (scraping backup)
- Cache local pour fiabilite

Usage:
    from utils.economic_calendar import (
        should_avoid_trading,
        get_upcoming_events,
        is_high_impact_window
    )

    # Verifier si on doit eviter de trader
    if should_avoid_trading("EURUSD"):
        print("Evenement economique proche - eviter le trading")
"""

from __future__ import annotations

import os
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class EconomicCalendarConfig:
    """Configuration du calendrier economique"""
    enabled: bool = True

    # Buffers en minutes
    buffer_before_high: int = 30      # 30 min avant evenement HIGH
    buffer_after_high: int = 15       # 15 min apres evenement HIGH
    buffer_before_medium: int = 15    # 15 min avant evenement MEDIUM
    buffer_after_medium: int = 5      # 5 min apres evenement MEDIUM

    # Filtrage
    min_impact_level: str = "MEDIUM"  # Ignorer les evenements LOW

    # Cache
    cache_ttl_minutes: int = 60       # Rafraichir le cache toutes les heures
    cache_file: str = "data/news_calendar.csv"

    # API
    api_timeout: int = 10
    fallback_to_static: bool = True   # Utiliser les evenements statiques si API echoue

    # Evenements critiques a toujours bloquer (mots-cles)
    critical_events: List[str] = field(default_factory=lambda: [
        "fomc", "nfp", "cpi", "gdp", "ecb", "boe", "rba", "boj",
        "interest rate", "employment", "inflation", "powell",
        "lagarde", "fed chair", "central bank"
    ])


# Mapping symboles -> devises impactees
SYMBOL_CURRENCIES = {
    # Forex
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "AUDUSD": ["AUD", "USD"],
    "USDCAD": ["USD", "CAD"],
    "USDCHF": ["USD", "CHF"],
    "NZDUSD": ["NZD", "USD"],
    "EURGBP": ["EUR", "GBP"],
    "EURJPY": ["EUR", "JPY"],
    "GBPJPY": ["GBP", "JPY"],

    # Commodities
    "XAUUSD": ["USD", "XAU"],
    "XAGUSD": ["USD", "XAG"],
    "USOUSD": ["USD"],
    "CL-OIL": ["USD"],

    # Indices (impactes par leur devise principale)
    "SP500": ["USD"],
    "NAS100": ["USD"],
    "DJ30": ["USD"],
    "UK100": ["GBP"],
    "GER40": ["EUR"],

    # Crypto (moins sensibles aux news macro mais quand meme)
    "BTCUSD": ["USD"],
    "ETHUSD": ["USD"],
    "SOLUSD": ["USD"],
    "ADAUSD": ["USD"],
    "BNBUSD": ["USD"],
    "LTCUSD": ["USD"],
}


@dataclass
class EconomicEvent:
    """Represente un evenement economique"""
    datetime_utc: datetime
    currency: str
    event_name: str
    impact: str  # HIGH, MEDIUM, LOW
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None

    def is_high_impact(self) -> bool:
        return self.impact.upper() == "HIGH"

    def is_critical(self, critical_keywords: List[str]) -> bool:
        name_lower = self.event_name.lower()
        return any(kw in name_lower for kw in critical_keywords)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "datetime_utc": self.datetime_utc.isoformat(),
            "currency": self.currency,
            "event_name": self.event_name,
            "impact": self.impact,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
        }


# =============================================================================
# CALENDRIER ECONOMIQUE
# =============================================================================

class EconomicCalendar:
    """Gestionnaire du calendrier economique"""

    def __init__(self, config: Optional[EconomicCalendarConfig] = None):
        self.config = config or EconomicCalendarConfig()
        self._events_cache: List[EconomicEvent] = []
        self._cache_timestamp: Optional[datetime] = None
        self._lock = threading.Lock()

        # Charger le cache depuis le fichier si disponible
        self._load_cache_from_file()

        logger.info(f"[ECON_CAL] Initialise, enabled={self.config.enabled}")

    def _load_cache_from_file(self) -> None:
        """Charge les evenements depuis le fichier cache"""
        cache_path = Path(self.config.cache_file)
        if not cache_path.exists():
            return

        try:
            import pandas as pd
            df = pd.read_csv(cache_path)

            events = []
            for _, row in df.iterrows():
                try:
                    dt = pd.to_datetime(row.get("datetime_utc", row.get("date", "")))
                    if pd.isna(dt):
                        continue

                    events.append(EconomicEvent(
                        datetime_utc=dt.to_pydatetime().replace(tzinfo=timezone.utc),
                        currency=str(row.get("currency", "USD")),
                        event_name=str(row.get("event_name", row.get("event", "Unknown"))),
                        impact=str(row.get("impact", "MEDIUM")).upper(),
                        actual=str(row.get("actual", "")) if pd.notna(row.get("actual")) else None,
                        forecast=str(row.get("forecast", "")) if pd.notna(row.get("forecast")) else None,
                        previous=str(row.get("previous", "")) if pd.notna(row.get("previous")) else None,
                    ))
                except Exception:
                    continue

            with self._lock:
                self._events_cache = events
                self._cache_timestamp = datetime.now(timezone.utc)

            logger.debug(f"[ECON_CAL] Charge {len(events)} evenements depuis cache")

        except Exception as e:
            logger.warning(f"[ECON_CAL] Erreur chargement cache: {e}")

    def _fetch_from_fxstreet(self) -> List[EconomicEvent]:
        """Recupere les evenements depuis FXStreet API"""
        events = []

        try:
            today = datetime.now(timezone.utc).date()
            tomorrow = today + timedelta(days=1)

            url = f"https://calendar-api.fxstreet.com/en/api/v1/eventDates"
            params = {
                "from": today.isoformat(),
                "to": tomorrow.isoformat()
            }

            response = requests.get(
                url,
                params=params,
                timeout=self.config.api_timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            if response.status_code != 200:
                logger.debug(f"[ECON_CAL] FXStreet API returned {response.status_code}")
                return events

            data = response.json()

            for item in data:
                try:
                    dt_str = item.get("dateUtc", "")
                    if not dt_str:
                        continue

                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

                    # Determiner l'impact
                    volatility = item.get("volatility", "").upper()
                    if volatility in ("HIGH", "3"):
                        impact = "HIGH"
                    elif volatility in ("MEDIUM", "MODERATE", "2"):
                        impact = "MEDIUM"
                    else:
                        impact = "LOW"

                    events.append(EconomicEvent(
                        datetime_utc=dt,
                        currency=item.get("currencyCode", "USD"),
                        event_name=item.get("name", "Unknown"),
                        impact=impact,
                        actual=item.get("actual"),
                        forecast=item.get("consensus"),
                        previous=item.get("previous"),
                    ))
                except Exception:
                    continue

            logger.debug(f"[ECON_CAL] Recupere {len(events)} evenements FXStreet")

        except requests.Timeout:
            logger.warning("[ECON_CAL] FXStreet API timeout")
        except Exception as e:
            logger.warning(f"[ECON_CAL] Erreur FXStreet API: {e}")

        return events

    def _get_static_events(self) -> List[EconomicEvent]:
        """Retourne les evenements statiques connus (backup)"""
        now = datetime.now(timezone.utc)
        today = now.date()

        # Evenements recurrents typiques (heures UTC)
        static = [
            # FOMC - generalement le mercredi
            EconomicEvent(
                datetime_utc=datetime(today.year, today.month, today.day, 19, 0, tzinfo=timezone.utc),
                currency="USD",
                event_name="FOMC Statement (if Wednesday)",
                impact="HIGH"
            ),
            # NFP - premier vendredi du mois
            EconomicEvent(
                datetime_utc=datetime(today.year, today.month, today.day, 13, 30, tzinfo=timezone.utc),
                currency="USD",
                event_name="Non-Farm Payrolls (if first Friday)",
                impact="HIGH"
            ),
            # ECB - generalement le jeudi
            EconomicEvent(
                datetime_utc=datetime(today.year, today.month, today.day, 12, 45, tzinfo=timezone.utc),
                currency="EUR",
                event_name="ECB Interest Rate Decision (if Thursday)",
                impact="HIGH"
            ),
        ]

        return [e for e in static if e.datetime_utc > now]

    def refresh_events(self, force: bool = False) -> None:
        """Rafraichit le cache des evenements"""
        now = datetime.now(timezone.utc)

        with self._lock:
            # Verifier si le cache est encore valide
            if not force and self._cache_timestamp:
                age = (now - self._cache_timestamp).total_seconds()
                if age < self.config.cache_ttl_minutes * 60:
                    return

        # Essayer de recuperer depuis l'API
        events = self._fetch_from_fxstreet()

        # Fallback vers les evenements statiques si API echoue
        if not events and self.config.fallback_to_static:
            events = self._get_static_events()

        with self._lock:
            if events:
                self._events_cache = events
            self._cache_timestamp = now

    def get_upcoming_events(
        self,
        currencies: Optional[List[str]] = None,
        hours_ahead: int = 24,
        min_impact: str = "MEDIUM"
    ) -> List[EconomicEvent]:
        """
        Retourne les evenements a venir.

        Args:
            currencies: Liste de devises a filtrer (None = toutes)
            hours_ahead: Horizon en heures
            min_impact: Impact minimum (HIGH, MEDIUM, LOW)
        """
        self.refresh_events()

        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=hours_ahead)

        impact_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        min_impact_level = impact_order.get(min_impact.upper(), 2)

        with self._lock:
            filtered = []
            for event in self._events_cache:
                # Filtre temporel
                if event.datetime_utc < now or event.datetime_utc > horizon:
                    continue

                # Filtre impact
                event_impact = impact_order.get(event.impact.upper(), 1)
                if event_impact < min_impact_level:
                    continue

                # Filtre devise
                if currencies and event.currency not in currencies:
                    continue

                filtered.append(event)

            return sorted(filtered, key=lambda e: e.datetime_utc)

    def is_in_event_window(
        self,
        symbol: str,
        check_time: Optional[datetime] = None
    ) -> Tuple[bool, Optional[EconomicEvent]]:
        """
        Verifie si on est dans une fenetre d'evenement pour un symbole.

        Returns:
            Tuple[in_window, event_if_any]
        """
        if not self.config.enabled:
            return False, None

        check_time = check_time or datetime.now(timezone.utc)
        currencies = SYMBOL_CURRENCIES.get(symbol.upper(), ["USD"])

        # Recuperer les evenements pour les devises concernees
        events = self.get_upcoming_events(
            currencies=currencies,
            hours_ahead=2,
            min_impact=self.config.min_impact_level
        )

        for event in events:
            # Determiner le buffer selon l'impact
            if event.impact.upper() == "HIGH" or event.is_critical(self.config.critical_events):
                before = timedelta(minutes=self.config.buffer_before_high)
                after = timedelta(minutes=self.config.buffer_after_high)
            else:
                before = timedelta(minutes=self.config.buffer_before_medium)
                after = timedelta(minutes=self.config.buffer_after_medium)

            window_start = event.datetime_utc - before
            window_end = event.datetime_utc + after

            if window_start <= check_time <= window_end:
                return True, event

        return False, None

    def should_avoid_trading(self, symbol: str) -> Tuple[bool, str]:
        """
        Determine si on doit eviter de trader.

        Returns:
            Tuple[should_avoid, reason]
        """
        in_window, event = self.is_in_event_window(symbol)

        if in_window and event:
            return True, f"Event proche: {event.event_name} ({event.currency} {event.impact})"

        return False, ""

    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut du calendrier"""
        now = datetime.now(timezone.utc)

        with self._lock:
            upcoming = [e for e in self._events_cache if e.datetime_utc > now][:5]

        return {
            "enabled": self.config.enabled,
            "cache_entries": len(self._events_cache),
            "cache_age_minutes": (
                (now - self._cache_timestamp).total_seconds() / 60
                if self._cache_timestamp else None
            ),
            "upcoming_events": [e.to_dict() for e in upcoming],
        }


# =============================================================================
# INSTANCE GLOBALE ET FONCTIONS UTILITAIRES
# =============================================================================

_calendar: Optional[EconomicCalendar] = None


def get_economic_calendar(
    config: Optional[EconomicCalendarConfig] = None
) -> EconomicCalendar:
    """Recupere ou cree l'instance globale du calendrier"""
    global _calendar

    if _calendar is None:
        _calendar = EconomicCalendar(config)

    return _calendar


def should_avoid_trading(symbol: str) -> Tuple[bool, str]:
    """
    Fonction utilitaire pour verifier si on doit eviter de trader.

    Usage:
        avoid, reason = should_avoid_trading("EURUSD")
        if avoid:
            print(f"Eviter le trading: {reason}")
    """
    cal = get_economic_calendar()
    return cal.should_avoid_trading(symbol)


def get_upcoming_events(
    symbol: Optional[str] = None,
    hours_ahead: int = 24
) -> List[Dict[str, Any]]:
    """
    Recupere les evenements a venir pour un symbole.

    Usage:
        events = get_upcoming_events("EURUSD", hours_ahead=4)
    """
    cal = get_economic_calendar()

    currencies = None
    if symbol:
        currencies = SYMBOL_CURRENCIES.get(symbol.upper(), ["USD"])

    events = cal.get_upcoming_events(
        currencies=currencies,
        hours_ahead=hours_ahead
    )

    return [e.to_dict() for e in events]


def is_high_impact_window(symbol: str) -> bool:
    """Verifie si on est dans une fenetre d'evenement HIGH impact"""
    cal = get_economic_calendar()
    in_window, event = cal.is_in_event_window(symbol)

    if in_window and event:
        return event.impact.upper() == "HIGH" or event.is_critical(
            cal.config.critical_events
        )

    return False
