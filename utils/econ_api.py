# utils/econ_api.py
"""
Client unifié pour le calendrier économique.

Sources (par priorité) :
  1. Finnhub /calendar/economic  (clé API requise, 60 appels/min)
  2. FXStreet calendar API       (gratuit, sans clé)

Cache TTL : 30 minutes (évite les appels excessifs).
Rate limiter : max 1 appel API / 60 s pour Finnhub.
"""
from __future__ import annotations

import os
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ── Cache en mémoire ────────────────────────────────────────────────────────
_CACHE_LOCK = threading.Lock()
_cache_data: List[Dict[str, Any]] = []
_cache_ts: float = 0.0
_CACHE_TTL: float = 1800.0  # 30 minutes

# ── Rate limiter Finnhub ────────────────────────────────────────────────────
_rate_lock = threading.Lock()
_last_finnhub_call: float = 0.0
_FINNHUB_MIN_INTERVAL: float = 60.0  # 1 appel / minute max


def _cache_get() -> Optional[List[Dict[str, Any]]]:
    with _CACHE_LOCK:
        if _cache_data and (time.time() - _cache_ts) < _CACHE_TTL:
            return list(_cache_data)
    return None


def _cache_set(events: List[Dict[str, Any]]) -> None:
    global _cache_data, _cache_ts
    with _CACHE_LOCK:
        _cache_data = list(events)
        _cache_ts = time.time()


def _finnhub_rate_ok() -> bool:
    """Retourne True si on peut appeler Finnhub (respecte le rate limit)."""
    global _last_finnhub_call
    with _rate_lock:
        now = time.time()
        if now - _last_finnhub_call >= _FINNHUB_MIN_INTERVAL:
            _last_finnhub_call = now
            return True
        return False


# ── Source 1 : Finnhub ──────────────────────────────────────────────────────

def _fetch_finnhub(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """
    Appelle Finnhub /calendar/economic et normalise les résultats.
    Réutilise connectors/finnhub_client.py si disponible, sinon appel direct.
    """
    if not _finnhub_rate_ok():
        logger.debug("[ECON_API] Finnhub rate limit interne — skip")
        return []

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.debug("[ECON_API] FINNHUB_API_KEY absente — skip Finnhub")
        return []

    # Tenter d'utiliser le client existant
    try:
        from connectors.finnhub_client import get_finnhub_client
        client = get_finnhub_client(api_key)
        events = client.get_economic_calendar(start_date=start, end_date=end)
        if events:
            logger.info(f"[ECON_API] Finnhub: {len(events)} événements via FinnhubClient")
            return _normalize_finnhub(events)
    except Exception as e:
        logger.debug(f"[ECON_API] FinnhubClient indisponible, fallback direct: {e}")

    # Fallback : appel HTTP direct
    try:
        import requests
        url = "https://finnhub.io/api/v1/calendar/economic"
        params = {
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
            "token": api_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 403:
            logger.debug("[ECON_API] Finnhub /calendar/economic: 403 (plan gratuit insuffisant) — fallback FXStreet/EventGuard")
            return []
        resp.raise_for_status()
        data = resp.json()
        raw_events = data.get("economicCalendar", [])
        logger.info(f"[ECON_API] Finnhub direct: {len(raw_events)} événements")
        return _normalize_finnhub(raw_events)
    except Exception as e:
        logger.warning(f"[ECON_API] Finnhub API error: {e}")
        return []


_COUNTRY_TO_CCY = {
    "US": "USD", "GB": "GBP", "EU": "EUR", "DE": "EUR", "FR": "EUR",
    "IT": "EUR", "ES": "EUR", "JP": "JPY", "CN": "CNY", "AU": "AUD",
    "CA": "CAD", "CH": "CHF", "NZ": "NZD",
}


def _normalize_finnhub(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalise les événements Finnhub vers le format unifié."""
    out: List[Dict[str, Any]] = []
    for ev in events:
        try:
            # Le client FinnhubClient renvoie déjà un format normalisé
            # avec les clés "event", "time", "impact", "currency", etc.
            # Si c'est le cas, on s'appuie dessus ; sinon on normalise le brut.
            if "currency" in ev and "event" in ev:
                # Déjà normalisé par FinnhubClient._normalize_calendar_events
                out.append({
                    "event": ev.get("event", ""),
                    "title": ev.get("event", ""),
                    "datetime": ev.get("time", ""),
                    "time": ev.get("time", ""),
                    "impact": (ev.get("impact", "") or "medium").lower(),
                    "currency": ev.get("currency", ""),
                    "country": ev.get("country", ""),
                    "actual": ev.get("actual"),
                    "forecast": ev.get("forecast") or ev.get("estimate"),
                    "previous": ev.get("previous") or ev.get("prev"),
                    "source": "finnhub",
                })
            else:
                # Format brut Finnhub API
                country = (ev.get("country", "") or "").upper()
                currency = _COUNTRY_TO_CCY.get(country, country)

                time_str = ev.get("time", "")
                date_str = ev.get("date", "")
                if time_str and date_str:
                    iso = f"{date_str}T{time_str}Z"
                elif date_str:
                    iso = f"{date_str}T00:00:00Z"
                else:
                    iso = time_str

                out.append({
                    "event": ev.get("event", ""),
                    "title": ev.get("event", ""),
                    "datetime": iso,
                    "time": iso,
                    "impact": (ev.get("impact", "") or "medium").lower(),
                    "currency": currency,
                    "country": country,
                    "actual": ev.get("actual"),
                    "forecast": ev.get("estimate"),
                    "previous": ev.get("prev"),
                    "source": "finnhub",
                })
        except Exception:
            continue
    return out


# ── Source 2 : FXStreet ─────────────────────────────────────────────────────

def _fetch_fxstreet(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """Fallback via FXStreet (réutilise utils/data_sources.py)."""
    try:
        from utils.data_sources import fetch_fxstreet_calendar
        raw = fetch_fxstreet_calendar(start=start, end=end, ttl=600.0)
        if not raw:
            return []
        logger.info(f"[ECON_API] FXStreet: {len(raw)} événements")
        return _normalize_fxstreet(raw)
    except Exception as e:
        logger.debug(f"[ECON_API] FXStreet fallback error: {e}")
        return []


def _normalize_fxstreet(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalise les événements FXStreet vers le format unifié."""
    out: List[Dict[str, Any]] = []
    for ev in events:
        try:
            impact_raw = str(ev.get("volatility", ev.get("impact", ""))).lower()
            if "high" in impact_raw:
                impact = "high"
            elif "medium" in impact_raw or "moderate" in impact_raw:
                impact = "medium"
            else:
                impact = "low"

            out.append({
                "event": ev.get("name", ev.get("event", ev.get("title", ""))),
                "title": ev.get("name", ev.get("event", ev.get("title", ""))),
                "datetime": ev.get("dateUtc", ev.get("time", ev.get("date", ""))),
                "time": ev.get("dateUtc", ev.get("time", ev.get("date", ""))),
                "impact": impact,
                "currency": ev.get("currencyCode", ev.get("currency", "")),
                "country": ev.get("countryCode", ev.get("country", "")),
                "actual": ev.get("actual"),
                "forecast": ev.get("consensus", ev.get("forecast")),
                "previous": ev.get("previous"),
                "source": "fxstreet",
            })
        except Exception:
            continue
    return out


# ── Source 3 : EventGuard (Investing / ForexFactory / CSV) ──────────────────

def _fetch_event_guard(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """Fallback via EventGuard (scrape Investing.com, ForexFactory, CSV local)."""
    try:
        from utils.event_guard import EventGuard
        guard = EventGuard()
        raw_events = guard.refresh_events(force=False)
        if not raw_events:
            return []
        out: List[Dict[str, Any]] = []
        for ev in raw_events:
            try:
                out.append({
                    "event": ev.title,
                    "title": ev.title,
                    "datetime": ev.timestamp.isoformat() if ev.timestamp else "",
                    "time": ev.timestamp.isoformat() if ev.timestamp else "",
                    "impact": ev.impact.value if hasattr(ev.impact, "value") else str(ev.impact).lower(),
                    "currency": ev.currency or "",
                    "country": "",
                    "actual": ev.actual,
                    "forecast": ev.forecast,
                    "previous": ev.previous,
                    "source": ev.source or "event_guard",
                })
            except Exception:
                continue
        logger.info(f"[ECON_API] EventGuard: {len(out)} événements")
        return out
    except Exception as e:
        logger.debug(f"[ECON_API] EventGuard fallback error: {e}")
        return []


# ── Client public ───────────────────────────────────────────────────────────

class EconCalendarClient:
    """
    Client unifié pour le calendrier économique.

    Usage :
        client = EconCalendarClient()
        events = client.events_between(start, end)

    Chaque événement retourné a la structure :
        {
            "event": str,         # ex: "Non-Farm Payrolls"
            "title": str,         # alias de event
            "datetime": str,      # ISO 8601 UTC
            "time": str,          # alias de datetime
            "impact": str,        # "high" | "medium" | "low"
            "currency": str,      # ex: "USD"
            "country": str,       # ex: "US"
            "actual": Any,        # valeur réelle (ou None)
            "forecast": Any,      # prévision (ou None)
            "previous": Any,      # valeur précédente (ou None)
            "source": str,        # "finnhub" | "fxstreet" | "event_guard"
        }
    """

    def __init__(self, **kwargs):
        pass

    def events_between(
        self,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Retourne les événements économiques entre *start* et *end* (UTC).

        Ordre de tentative :
          1. Cache mémoire (TTL 30 min)
          2. Finnhub API (rate-limited à 1 appel/min)
          3. FXStreet API (fallback)
          4. EventGuard (Investing.com / ForexFactory / CSV local)
        """
        # 1) Cache
        cached = _cache_get()
        if cached is not None:
            return _filter_window(cached, start, end)

        # 2) Finnhub (source principale)
        events = _fetch_finnhub(start, end)

        # 3) FXStreet (fallback)
        if not events:
            events = _fetch_fxstreet(start, end)

        # 4) EventGuard (Investing/ForexFactory/CSV)
        if not events:
            events = _fetch_event_guard(start, end)

        # Stocker en cache même si vide (évite de re-appeler pendant le TTL)
        if events:
            _cache_set(events)

        return _filter_window(events, start, end)


def _filter_window(
    events: List[Dict[str, Any]],
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    """Filtre les événements dans la fenêtre [start, end]."""
    out: List[Dict[str, Any]] = []
    for ev in events:
        ts = ev.get("datetime") or ev.get("time") or ""
        if not ts:
            out.append(ev)  # pas de date → on garde par défaut
            continue
        try:
            t = _parse_dt(ts)
            if t is None or (start <= t <= end):
                out.append(ev)
        except Exception:
            out.append(ev)
    return out


def _parse_dt(s: str) -> Optional[datetime]:
    """Parse une date ISO-ish vers un datetime UTC."""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return d
        except Exception:
            continue
    return None
