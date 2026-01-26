#!/usr/bin/env python
"""
Export MT5 closed trades to an Excel file compatible with ReportHistory-10960352.

The generated workbook keeps the metadata/header structure that the existing
guards rely on so scripts such as daily_guard.py and daily_performance_tracker.py
can consume it transparently.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from zoneinfo import ZoneInfo

import MetaTrader5 as mt5  # type: ignore
from openpyxl import Workbook

from utils.mt5_client import MT5Client

LOCAL_TZ = ZoneInfo("Europe/Zurich")
UTC = timezone.utc

HEADER_ROW = [
    "Heure",
    "Position",
    "Symbole",
    "Type",
    "Volume",
    "Prix",
    "S / L",
    "T / P",
    "Heure.1",
    "Prix.1",
    "Commission",
    "Echange",
    "Profit",
    "Unnamed: 13",
]


def _fmt_dt(ts: float) -> str:
    dt = datetime.fromtimestamp(float(ts), tz=UTC).astimezone(LOCAL_TZ)
    return dt.strftime("%Y.%m.%d %H:%M:%S")


def _type_to_str(deal_type: Optional[int]) -> str:
    if deal_type == getattr(mt5, "DEAL_TYPE_BUY", 0):
        return "buy"
    if deal_type == getattr(mt5, "DEAL_TYPE_SELL", 1):
        return "sell"
    return str(deal_type or "")


def _collect_deals(start: datetime, end: datetime) -> Iterable:
    deals = mt5.history_deals_get(start, end)
    if deals is None:
        raise RuntimeError("history_deals_get a retourné None (session MT5 invalide ?)")
    return deals


def _split_deals(deals: Iterable) -> Tuple[dict, List]:
    """Returns (opens_by_position, closing_deals)."""
    opens: dict[int, List] = defaultdict(list)
    closings: List = []
    entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
    entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    for deal in deals:
        pos_id = int(getattr(deal, "position_id", 0) or 0)
        if pos_id <= 0:
            continue
        entry = getattr(deal, "entry", None)
        if entry == entry_in:
            opens[pos_id].append(deal)
            opens[pos_id].sort(key=lambda d: getattr(d, "time", 0))
        elif entry == entry_out and float(getattr(deal, "volume", 0.0) or 0.0) > 0:
            closings.append(deal)
    closings.sort(key=lambda d: getattr(d, "time", 0))
    return opens, closings


def _build_rows(opens: dict, closings: Iterable) -> List[List]:
    rows: List[List] = []
    for deal in closings:
        pos_id = int(getattr(deal, "position_id", 0) or 0)
        open_deal = (opens.get(pos_id) or [None])[0]
        open_time = getattr(open_deal, "time", getattr(deal, "time", 0))
        close_time = getattr(deal, "time", 0)
        open_price = getattr(open_deal, "price", getattr(deal, "price", 0.0) or 0.0)
        close_price = getattr(deal, "price", 0.0) or 0.0
        trade_type = _type_to_str(getattr(open_deal or deal, "type", None))
        volume = float(getattr(deal, "volume", 0.0) or 0.0)
        commission = float(getattr(deal, "commission", 0.0) or 0.0)
        swap = float(getattr(deal, "swap", 0.0) or 0.0)
        profit = float(getattr(deal, "profit", 0.0) or 0.0)
        comment = getattr(deal, "comment", "") or ""

        rows.append(
            [
                _fmt_dt(open_time),
                pos_id,
                getattr(deal, "symbol", "") or "",
                trade_type,
                volume,
                open_price,
                None,
                None,
                _fmt_dt(close_time),
                close_price,
                commission,
                swap,
                profit,
                comment,
            ]
        )
    return rows


def _write_workbook(rows: List[List], output_path: Path, account_info) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    now_txt = datetime.now(LOCAL_TZ).strftime("%Y.%m.%d %H:%M")
    ws.append(["Rapport d'historique de trading"])
    ws.append(["Nom:", None, None, getattr(account_info, "name", "") or ""])
    account_line = f"{getattr(account_info, 'login', '')} ({getattr(account_info, 'currency', '')}, {getattr(account_info, 'server', '')})"
    ws.append(["Compte:", None, None, account_line])
    ws.append(["Courtier:", None, None, getattr(account_info, "company", "") or getattr(account_info, "server", "")])
    ws.append(["Date:", None, None, now_txt])
    ws.append(["Positions"])
    ws.append(HEADER_ROW)

    for row in rows:
        ws.append(row)

    wb.save(output_path)


def export_history(days: int, output_path: Path) -> Path:
    MT5Client.initialize_if_needed()
    client = MT5Client()  # noqa: F841 - ensure login context

    account_info = mt5.account_info()
    if account_info is None:
        raise RuntimeError("Impossible de lire account_info MT5.")

    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    deals = _collect_deals(start, end)
    opens, closings = _split_deals(deals)
    rows = _build_rows(opens, closings)
    _write_workbook(rows, output_path, account_info)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export automatique ReportHistory-10960352 depuis MT5.")
    parser.add_argument("--days", type=int, default=60, help="Nombre de jours d'historique à extraire.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports") / "ReportHistory-10960352.xlsx",
        help="Chemin de sortie du rapport.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = export_history(days=max(1, args.days), output_path=Path(args.output))
    print(f"[export_report_history] {output} mis à jour.")


if __name__ == "__main__":
    main()
