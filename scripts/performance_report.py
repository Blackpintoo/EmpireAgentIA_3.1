"""Performance reporting script for EmpireAgentIA.

Usage examples:
    python -m scripts.performance_report --start 2025-09-01 --end 2025-09-30
    python -m scripts.performance_report --symbols BTCUSD ETHUSD --days 7

Outputs an ASCII table with aggregate metrics per symbol and account-wide.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

DATE_FMT = "%Y-%m-%d"
TS_FMT = "%Y-%m-%dT%H:%M:%S"
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
AUDIT_DIR = DATA_DIR / "audit"
TRADES_CSV = DATA_DIR / "trades_log.csv"
EQUITY_CSV = DATA_DIR / "equity_log.csv"


@dataclass
class TradeStats:
    attempts: int = 0
    executed: int = 0
    failed: int = 0
    avg_lot: float = 0.0

    def update(self, lots: Optional[float], ok: bool) -> None:
        self.attempts += 1
        if ok:
            self.executed += 1
            if lots is not None:
                # incremental average
                if self.avg_lot == 0.0:
                    self.avg_lot = lots
                else:
                    self.avg_lot = ((self.avg_lot * (self.executed - 1)) + lots) / self.executed
        else:
            self.failed += 1

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.executed / self.attempts


@dataclass
class PnLStats:
    pnl: float = 0.0
    trades: int = 0

    def update(self, pnl: float) -> None:
        self.pnl += pnl
        self.trades += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EmpireAgentIA performance report")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (exclusive)")
    parser.add_argument("--days", type=int, help="Alternative to start/end: look back N days", default=None)
    parser.add_argument("--symbols", nargs="*", help="Symbols to include (default: all detected)")
    parser.add_argument("--csv", type=Path, help="Optional path to export CSV summary")
    return parser.parse_args()


def parse_date_range(args: argparse.Namespace) -> Tuple[datetime, datetime]:
    if args.start and args.end:
        start = datetime.strptime(args.start, DATE_FMT).replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end, DATE_FMT).replace(tzinfo=timezone.utc)
    else:
        days = args.days or 7
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
    if end <= start:
        raise ValueError("End date must be after start date")
    return start, end


def load_trades(start: datetime, end: datetime, symbols: Optional[Iterable[str]]) -> Dict[str, TradeStats]:
    stats: Dict[str, TradeStats] = defaultdict(TradeStats)
    if not TRADES_CSV.exists():
        return stats

    with TRADES_CSV.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts_str = row.get("ts_utc")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            if ts < start or ts >= end:
                continue

            symbol = (row.get("symbol") or "").upper()
            if symbols and symbol not in symbols:
                continue

            lots = None
            try:
                lots = float(row.get("lots") or 0.0)
            except Exception:
                lots = None

            retcode = row.get("retcode")
            ok = str(row.get("ok") or "").strip().lower() in {"1", "true", "yes"}
            # fall back: Trade retcode 10009 considered success
            if not ok and retcode and retcode.isdigit():
                ok = int(retcode) == 10009

            stats[symbol].update(lots, ok)

    return stats


def discover_symbols(trades_stats: Dict[str, TradeStats]) -> List[str]:
    symbols = sorted(trades_stats.keys())
    return symbols


def load_audit_pnl(start: datetime, end: datetime, symbols: Optional[Iterable[str]]) -> Dict[str, PnLStats]:
    stats: Dict[str, PnLStats] = defaultdict(PnLStats)
    if not AUDIT_DIR.exists():
        return stats

    symbols_set = set(s.upper() for s in symbols) if symbols else None

    for path in sorted(AUDIT_DIR.glob("audit_*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_str = rec.get("ts")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
                if ts < start or ts >= end:
                    continue

                symbol = (rec.get("symbol") or rec.get("payload", {}).get("symbol") or "").upper()
                if symbols_set and symbol not in symbols_set:
                    continue

                event = rec.get("event", "").upper()
                payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else rec

                if event in {"CLOSE_TRADE", "CLOSE_TRADE_SIM"}:
                    pnl_val = payload.get("pnl_ccy") or payload.get("profit_ccy") or payload.get("pnl")
                    try:
                        pnl = float(pnl_val)
                    except (TypeError, ValueError):
                        continue
                    stats[symbol].update(pnl)
                elif event == "NEW_TRADE_SIM":
                    # dry run entries: track count but zero pnl (optional)
                    stats[symbol]

    return stats


def load_equity_series(start: datetime, end: datetime) -> Tuple[Optional[float], Optional[float]]:
    if not EQUITY_CSV.exists():
        return None, None
    try:
        df = pd.read_csv(EQUITY_CSV, parse_dates=["ts_utc"])
    except Exception as exc:
        print(f"[performance_report] equity CSV lecture échouée: {exc}")
        return None, None
    df = df[(df["ts_utc"] >= start) & (df["ts_utc"] < end)]
    if df.empty:
        return None, None
    start_eq = float(df.iloc[0]["equity"])
    end_eq = float(df.iloc[-1]["equity"])
    return start_eq, end_eq


def format_float(v: Optional[float], precision: int = 2) -> str:
    if v is None:
        return "-"
    return f"{v:.{precision}f}"


def build_table(symbols: List[str], trade_stats: Dict[str, TradeStats], pnl_stats: Dict[str, PnLStats]) -> List[List[str]]:
    headers = ["Symbol", "Attempts", "Executed", "Success %", "Avg lot", "PNL", "Trades"]
    rows = [headers]
    for sym in symbols:
        t = trade_stats.get(sym, TradeStats())
        p = pnl_stats.get(sym, PnLStats())
        rows.append([
            sym,
            str(t.attempts),
            str(t.executed),
            format_float(t.success_rate * 100.0),
            format_float(t.avg_lot, precision=3),
            format_float(p.pnl),
            str(p.trades),
        ])
    return rows


def print_table(rows: List[List[str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for idx, row in enumerate(rows):
        line = " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        print(line)
        if idx == 0:
            print("-+-".join("-" * width for width in widths))


def export_csv(rows: List[List[str]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)
    print(f"Exported summary to {path}")



def generate_report(start, end, symbols=None):
    """Return report data for reuse."""
    trade_stats = load_trades(start, end, symbols)
    final_symbols = symbols or discover_symbols(trade_stats)
    final_symbols = sorted(set(s.upper() for s in final_symbols))
    pnl_stats = load_audit_pnl(start, end, final_symbols or None)
    equity_start, equity_end = load_equity_series(start, end)
    rows = build_table(final_symbols, trade_stats, pnl_stats)
    return rows, equity_start, equity_end, trade_stats, pnl_stats, final_symbols


def main() -> None:
    args = parse_args()
    start, end = parse_date_range(args)

    rows, equity_start, equity_end, trade_stats, pnl_stats, symbols = generate_report(start, end, args.symbols)

    if not symbols:
        print("Aucun symbole détecté dans la période donnée.")
        return

    print_table(rows)

    if equity_start is not None and equity_end is not None:
        delta = equity_end - equity_start
        pct = (delta / equity_start * 100.0) if equity_start else 0.0
        print()
        print(f"Equity start: {equity_start:.2f} | Equity end: {equity_end:.2f} | Delta={delta:.2f} ({pct:.2f}%)")

    if args.csv:
        export_csv(rows, args.csv)


if __name__ == "__main__":
    main()
