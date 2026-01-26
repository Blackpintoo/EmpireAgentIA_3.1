"""Aggregate executed trades from audit logs into a daily journal CSV/JSON."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Iterable, List

AUDIT_DIR = Path("data") / "audit"
JOURNAL_DIR = Path("data") / "journal"


def iter_audit_records() -> Iterable[Dict[str, Any]]:
    if not AUDIT_DIR.exists():
        return []
    for path in sorted(AUDIT_DIR.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build trade journal from audit logs")
    parser.add_argument("--date", help="Target date (UTC, YYYY-MM-DD)")
    parser.add_argument("--start", help="Start date (inclusive, UTC)")
    parser.add_argument("--end", help="End date (inclusive, UTC)")
    parser.add_argument("--include-sim", action="store_true", help="Include #CLOSE_TRADE_SIM events")
    parser.add_argument("--summary", action="store_true", help="Print an aggregated summary")
    parser.add_argument("--export-csv", type=Path, help="Export aggregated CSV over the selected range")
    parser.add_argument("--export-json", type=Path, help="Export aggregated JSON over the selected range")
    return parser.parse_args()


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def extract_records(day: datetime, include_sim: bool) -> List[Dict[str, Any]]:
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    out: List[Dict[str, Any]] = []

    for rec in iter_audit_records():
        event = str(rec.get("event", "")).upper()
        if event not in {"CLOSE_TRADE", "CLOSE_TRADE_SIM"}:
            continue
        if event == "CLOSE_TRADE_SIM" and not include_sim:
            continue
        ts_raw = rec.get("ts") or rec.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not (day_start <= ts < day_end):
            continue

        payload = rec.get("payload") or {}
        record = {
            "timestamp": ts.isoformat(),
            "symbol": payload.get("symbol") or rec.get("symbol"),
            "side": payload.get("side"),
            "lots": payload.get("lots"),
            "entry": payload.get("entry"),
            "exit": payload.get("exit") or payload.get("exit_price"),
            "sl": payload.get("sl"),
            "tp": payload.get("tp"),
            "rr": payload.get("rr") or payload.get("reward_risk"),
            "pnl": payload.get("pnl") or payload.get("pnl_ccy") or payload.get("profit"),
            "retcode": payload.get("retcode"),
            "source": payload.get("strategy") or payload.get("regime") or rec.get("source"),
        }
        out.append(record)
    return out


def write_daily_outputs(day: datetime, rows: List[Dict[str, Any]]) -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    day_str = day.strftime("%Y-%m-%d")

    json_path = JOURNAL_DIR / f"trades_{day_str}.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = JOURNAL_DIR / f"trades_{day_str}.csv"
    if rows:
        headers = list(rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    else:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            fh.write("timestamp,symbol,side,lots,entry,exit,sl,tp,rr,pnl,retcode,source\n")

    print(f"Journal saved: {json_path} ({len(rows)} trades)")
    print(f"Journal saved: {csv_path} ({len(rows)} trades)")


def summarise(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("No trades to summarise.")
        return
    total_trades = len(rows)
    pnl = 0.0
    per_symbol = {}
    for row in rows:
        try:
            val = float(row.get("pnl") or 0.0)
        except (TypeError, ValueError):
            val = 0.0
        pnl += val
        sym = (row.get("symbol") or "UNKNOWN").upper()
        per_symbol.setdefault(sym, {"count": 0, "pnl": 0.0})
        per_symbol[sym]["count"] += 1
        per_symbol[sym]["pnl"] += val

    print(f"Total trades: {total_trades}")
    print(f"Net PnL: {pnl:.2f} USD")
    print("PnL by symbol:")
    for sym, info in sorted(per_symbol.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
        print(f"  {sym}: trades={info['count']} | pnl={info['pnl']:.2f}")


def main() -> None:
    args = parse_args()
    dates: List[datetime]
    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("--start and --end must be provided together")
        start = parse_date(args.start)
        end = parse_date(args.end)
        if end < start:
            raise SystemExit("--end must be >= --start")
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    else:
        target = parse_date(args.date) if args.date else datetime.now(timezone.utc)
        dates = [target]

    aggregated: List[Dict[str, Any]] = []
    for day in dates:
        rows = extract_records(day, include_sim=args.include_sim)
        write_daily_outputs(day, rows)
        aggregated.extend(rows)

    if args.summary:
        summarise(aggregated)

    if args.export_csv and aggregated:
        args.export_csv.parent.mkdir(parents=True, exist_ok=True)
        headers = list(aggregated[0].keys())
        with args.export_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
            writer.writerows(aggregated)
        print(f"Aggregated CSV exported to {args.export_csv}")

    if args.export_json and aggregated:
        args.export_json.parent.mkdir(parents=True, exist_ok=True)
        args.export_json.write_text(json.dumps(aggregated, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Aggregated JSON exported to {args.export_json}")


if __name__ == "__main__":
    main()
