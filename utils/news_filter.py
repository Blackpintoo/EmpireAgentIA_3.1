# utils/news_filter.py
from __future__ import annotations
import csv, os
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Iterable, Optional, List, Dict, Any, Tuple

TZ = ZoneInfo("Europe/Zurich")

@dataclass
class NewsEvent:
    ts: datetime            # aware (Europe/Zurich)
    currency: str           # ex: USD, EUR
    impact: str             # High/Medium/Low
    title: str

def _parse_row(row: Dict[str, str]) -> Optional[NewsEvent]:
    """
    CSV attendu (UTF-8):
    datetime,currency,impact,title
    2025-08-31 14:30,USD,High,Non-Farm Payrolls
    """
    try:
        dt = datetime.strptime(row["datetime"].strip(), "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=TZ)
        currency = (row.get("currency") or "").upper().strip()
        impact   = (row.get("impact") or "").capitalize().strip()
        title    = (row.get("title") or "").strip()
        if not currency or not impact:
            return None
        return NewsEvent(ts=dt, currency=currency, impact=impact, title=title)
    except Exception:
        return None

def load_news_csv(path: str) -> List[NewsEvent]:
    if not os.path.exists(path):
        return []
    out: List[NewsEvent] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ev = _parse_row(row)
            if ev:
                out.append(ev)
    return out

# Mapping simple symbole -> devises exposées
# (peut être surchargé dans profiles.yaml/overrides.yaml si besoin)
DEFAULT_SYMBOL_CCY = {
    "BTCUSD": {"USD"},
    "ETHUSD": {"USD"},
    "LTCUSD": {"USD"},
    "BNBUSD": {"USD"},
    "XAUUSD": {"USD"},
    "EURUSD": {"EUR", "USD"},
    "DJ30": {"USD"},
    "CL-OIL": {"USD"},
}

def symbol_currencies(symbol_canon: str, profile: Dict[str, Any]) -> Iterable[str]:
    # permet override côté profile: instrument.currencies: [USD, EUR]
    inst = profile.get("instrument") or {}
    cur = inst.get("currencies")
    if isinstance(cur, (list, tuple, set)) and cur:
        return {str(x).upper() for x in cur}
    return DEFAULT_SYMBOL_CCY.get(symbol_canon.upper(), {"USD"})

def is_frozen_now(
    *,
    symbol: str,
    profile: Dict[str, Any],
    news_csv: str = "data/news_calendar.csv",
    window_before_min: int = 15,
    window_after_min: int  = 15,
    impacts: Iterable[str] = ("High",),
    now: Optional[datetime] = None,
    manual_freezes: Iterable[Tuple[str, str]] = ()
) -> Tuple[bool, str]:
    """
    Renvoie (frozen, reason). 'reason' utile pour Telegram.
    - manual_freezes: liste de tuples (start_iso, end_iso) en TZ Europe/Zurich
    """
    impacts = {s.capitalize() for s in impacts}
    now = now or datetime.now(TZ)
    # 1) fenêtres manuelles
    for start_iso, end_iso in manual_freezes:
        try:
            s = datetime.fromisoformat(start_iso).astimezone(TZ)
            e = datetime.fromisoformat(end_iso).astimezone(TZ)
            if s <= now <= e:
                return True, f"manual_freeze {start_iso}→{end_iso}"
        except Exception:
            continue

    # 2) news CSV
    evs = load_news_csv(news_csv)
    if not evs:
        return (False, "")

    ccys = set(symbol_currencies(symbol, profile))

    for ev in evs:
        if ev.impact not in impacts:
            continue
        if ev.currency not in ccys:
            continue
        s = ev.ts - timedelta(minutes=window_before_min)
        e = ev.ts + timedelta(minutes=window_after_min)
        if s <= now <= e:
            return True, f"{ev.currency}/{ev.impact}: {ev.title} @ {ev.ts.strftime('%Y-%m-%d %H:%M %Z')}"
    return (False, "")
