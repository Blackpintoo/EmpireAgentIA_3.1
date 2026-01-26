"""Generate insights from data/performance/performance_tracker.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any, List

TRACKER_PATH = Path("data") / "performance" / "performance_tracker.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise performance tracker weights")
    parser.add_argument("--symbol", nargs="*", help="Filter by symbol(s)")
    parser.add_argument("--top", type=int, default=10, help="Display top N buckets")
    parser.add_argument("--bottom", type=int, default=10, help="Display bottom N buckets")
    parser.add_argument("--min-count", type=int, default=5, help="Minimum trades required")
    parser.add_argument("--csv", type=Path, help="Optional path to export flattened data")
    return parser.parse_args()


def load_tracker() -> Dict[str, Any]:
    if not TRACKER_PATH.exists():
        raise SystemExit(f"Tracker file not found: {TRACKER_PATH}")
    return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))


def flatten(data: Dict[str, Any], symbols: List[str], min_count: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    symbols_filter = {s.upper() for s in symbols} if symbols else None
    for symbol, agents in data.items():
        if symbols_filter and symbol.upper() not in symbols_filter:
            continue
        for agent, buckets in (agents or {}).items():
            for bucket, stats in (buckets or {}).items():
                count = int(stats.get("count", 0) or 0)
                if count < min_count:
                    continue
                rows.append({
                    "symbol": symbol,
                    "agent": agent,
                    "bucket": bucket,
                    "count": count,
                    "weight": float(stats.get("weight", 0.0) or 0.0),
                    "win_rate": float(stats.get("win_rate", 0.0) or 0.0),
                    "score_ema": float(stats.get("score_ema", 0.0) or 0.0),
                    "outcome_ema": float(stats.get("outcome_ema", 0.0) or 0.0),
                    "last_update": stats.get("last_update"),
                })
    return rows


def render_table(title: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print(f"{title}: no data")
        return
    headers = ["symbol", "agent", "bucket", "count", "weight", "win_rate", "outcome_ema"]
    widths = {h: max(len(h), *(len(f"{row.get(h, '')}") for row in rows)) for h in headers}
    print(title)
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print(" | ".join(f"{row.get(h, '')}".ljust(widths[h]) for h in headers))
    print()


def main() -> None:
    args = parse_args()
    tracker = load_tracker()
    rows = flatten(tracker, args.symbol or [], args.min_count)
    if not rows:
        print("No tracker entries match the filters.")
        return
    rows.sort(key=lambda r: r["weight"], reverse=True)
    top_rows = rows[: args.top]
    bottom_rows = sorted(rows, key=lambda r: r["weight"])[: args.bottom]

    render_table("Top buckets", top_rows)
    render_table("Bottom buckets", bottom_rows)

    symbols_summary: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        summary = symbols_summary.setdefault(
            row["symbol"], {"count": 0, "total_weight": 0.0, "avg_win": 0.0, "entries": 0}
        )
        summary["count"] += row["count"]
        summary["total_weight"] += row["weight"]
        summary["avg_win"] += row["win_rate"]
        summary["entries"] += 1
    print("Summary by symbol (avg weight, avg win rate, total count):")
    for symbol, summary in sorted(symbols_summary.items(), key=lambda kv: kv[1]["total_weight"], reverse=True):
        entries = summary["entries"] or 1
        avg_weight = summary["total_weight"] / entries
        avg_win = summary["avg_win"] / entries
        print(f"  {symbol}: avgWeight={avg_weight:.2f} | avgWin%={avg_win:.1f} | trades={summary['count']}")

    if args.csv:
        import csv
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Exported full tracker data to {args.csv}")


if __name__ == "__main__":
    main()
