#!/usr/bin/env python
"""
Télécharge le calendrier ForexFactory (format CSV) et génère
data/news_calendar.csv compatible avec utils.news_filter.
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import requests
from zoneinfo import ZoneInfo


NY_TZ = ZoneInfo("America/New_York")
TARGET_TZ = ZoneInfo("Europe/Zurich")
DEFAULT_OUTPUT = Path("data/news_calendar.csv")
DEFAULT_SOURCES: Tuple[str, ...] = ("this",)
SOURCE_MAP = {
    "this": "https://nfs.faireconomy.media/ff_calendar_thisweek.csv",
    "next": "https://nfs.faireconomy.media/ff_calendar_thisweek.csv?week=next",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
}


@dataclass
class CalendarRow:
    dt: datetime
    currency: str
    impact: str
    title: str
    source: str
    url: Optional[str]

    def to_csv_row(self) -> List[str]:
        return [
            self.dt.astimezone(TARGET_TZ).strftime("%Y-%m-%d %H:%M"),
            self.currency,
            self.impact,
            self.title,
            self.source,
            self.url or "",
        ]


def fetch_csv(source: str, *, delay_on_429: float = 10.0, retries: int = 4) -> Sequence[dict]:
    url = SOURCE_MAP.get(source)
    if not url:
        raise ValueError(f"Source inconnue: {source}")
    for attempt in range(1, retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt == retries:
                raise RuntimeError(f"Rate limit ForexFactory sur {url}")
            time.sleep(delay_on_429 * attempt)
            continue
        resp.raise_for_status()
        text = resp.text
        reader = csv.DictReader(text.splitlines())
        return list(reader)
    return []


def _parse_time(time_str: str) -> Optional[Tuple[int, int]]:
    clean = (time_str or "").strip().lower()
    if clean in ("", "all day", "day", "tentative", "tba", "unscheduled", "n/a"):
        return (0, 0)
    for fmt in ("%I:%M%p", "%I%p"):
        try:
            tm = datetime.strptime(clean, fmt)
            return tm.hour, tm.minute
        except ValueError:
            continue
    return None


def parse_row(row: dict, source: str) -> Optional[CalendarRow]:
    try:
        date_raw = row.get("Date", "").strip()
        time_raw = row.get("Time", "").strip()
        currency = (row.get("Country") or "").strip().upper()
        impact = (row.get("Impact") or "").strip().capitalize()
        title = (row.get("Title") or "").strip()
        url = (row.get("URL") or "").strip() or None
        if not date_raw or not currency or not title:
            return None
        base_date = datetime.strptime(date_raw, "%m-%d-%Y")
        hhmm = _parse_time(time_raw)
        if hhmm is None:
            return None
        hour, minute = hhmm
        dt = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            hour,
            minute,
            tzinfo=NY_TZ,
        ).astimezone(TARGET_TZ)
        return CalendarRow(
            dt=dt,
            currency=currency,
            impact=impact or "Unspecified",
            title=title,
            source=source,
            url=url,
        )
    except Exception:
        return None


def consolidate(rows: Iterable[CalendarRow]) -> List[CalendarRow]:
    unique = {}
    for row in rows:
        key = (row.dt, row.currency, row.impact, row.title)
        if key not in unique:
            unique[key] = row
    return sorted(unique.values(), key=lambda r: r.dt)


def write_csv(rows: List[CalendarRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "currency", "impact", "title", "source", "url"])
        for row in rows:
            writer.writerow(row.to_csv_row())


def parse_sources(raw: Optional[str]) -> Tuple[str, ...]:
    if not raw:
        return DEFAULT_SOURCES
    items = [s.strip().lower() for s in raw.split(",") if s.strip()]
    if not items:
        return DEFAULT_SOURCES
    return tuple(items)


def main() -> None:
    parser = argparse.ArgumentParser(description="Met à jour data/news_calendar.csv depuis ForexFactory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Fichier CSV de sortie.")
    parser.add_argument(
        "--sources",
        type=str,
        help="Sources à récupérer (séparées par des virgules). Valeurs reconnues: this, next.",
    )
    parser.add_argument("--verbose", action="store_true", help="Affiche les événements retenus.")
    args = parser.parse_args()

    rows: List[CalendarRow] = []
    sources = parse_sources(args.sources)
    for source in sources:
        try:
            raw_rows = fetch_csv(source)
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] Échec récupération {source}: {exc}")
            continue
        for row in raw_rows:
            ev = parse_row(row, source=source)
            if ev:
                rows.append(ev)
    consolidated = consolidate(rows)
    if not consolidated:
        if args.output.exists():
            print("[WARN] Aucun nouvel événement récupéré. L'ancien fichier est conservé.")
            return
        raise SystemExit("Aucun événement valide récupéré.")
    write_csv(consolidated, args.output)
    print(f"[INFO] {len(consolidated)} événements sauvegardés dans {args.output}")
    if args.verbose:
        for ev in consolidated[:10]:
            print(f" - {ev.dt:%Y-%m-%d %H:%M} | {ev.currency} | {ev.impact} | {ev.title}")


if __name__ == "__main__":
    main()
