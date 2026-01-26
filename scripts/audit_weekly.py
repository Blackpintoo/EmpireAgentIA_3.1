"""
Generate a 7-day performance overview by aggregating audit logs.

Example:
    python scripts/audit_weekly.py --days 7 --output reports/weekly_audit.txt
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from utils.performance_tracker import PerformanceTracker

AUDIT_DIR = Path("data") / "audit"
DEFAULT_OUTPUT = Path("reports") / "weekly_audit.txt"
SUCCESS_CODES = {10008, 10009}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a weekly performance snapshot.")
    parser.add_argument("--days", type=int, default=7, help="Number of trailing days to include.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination report path (default: reports/weekly_audit.txt).",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=AUDIT_DIR,
        help="Folder containing audit_YYYY-MM-DD.jsonl files.",
    )
    return parser.parse_args()


def _iter_audit_files(root: Path, days: int) -> List[Tuple[datetime, Path]]:
    end = datetime.now()
    files: List[Tuple[datetime, Path]] = []
    for delta in range(days):
        day = end - timedelta(days=delta)
        fname = f"audit_{day.strftime('%Y-%m-%d')}.jsonl"
        fpath = root / fname
        files.append((day, fpath))
    return files


def _load_records(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records: List[Dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return records


def _aggregate(records: List[Dict]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rr_cache: Dict[str, List[float]] = defaultdict(list)

    for rec in records:
        if rec.get("event") != "TRADE_EXEC":
            continue
        symbol = str(rec.get("symbol") or "UNKNOWN").upper()
        result = rec.get("result") or {}
        retcode = result.get("retcode")
        if retcode is None and isinstance(result.get("retcode_external"), int):
            retcode = int(result["retcode_external"])

        stats[symbol]["trades"] += 1
        if bool(result.get("ok")) or (retcode in SUCCESS_CODES):
            stats[symbol]["executed"] += 1
        if isinstance(retcode, int):
            key = f"retcode_{retcode}"
            stats[symbol][key] += 1

        entry = rec.get("price")
        sl = rec.get("sl")
        tp = rec.get("tp")
        try:
            if entry is not None and sl is not None and tp is not None:
                entry_f = float(entry)
                sl_f = float(sl)
                tp_f = float(tp)
                risk = abs(entry_f - sl_f)
                reward = abs(tp_f - entry_f)
                if risk > 0:
                    rr_cache[symbol].append(reward / risk)
        except Exception:
            continue

    for symbol, ratios in rr_cache.items():
        if ratios:
            stats[symbol]["rr_avg"] = sum(ratios) / len(ratios)
            stats[symbol]["rr_count"] = len(ratios)
    return stats


def _build_report(days: int, stats: Dict[str, Dict[str, float]], tracker: PerformanceTracker) -> str:
    end = datetime.now()
    start = end - timedelta(days=days - 1)
    lines: List[str] = []
    lines.append("Empire Agent IA - Weekly Audit")
    lines.append(f"Période analysée : {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
    lines.append("")

    total_trades = sum(int(v.get("trades", 0)) for v in stats.values())
    total_exec = sum(int(v.get("executed", 0)) for v in stats.values())
    lines.append("Résumé global")
    lines.append(f"- Trades détectés : {total_trades}")
    exec_ratio = (total_exec / total_trades * 100.0) if total_trades else 0.0
    lines.append(f"- Exécutions confirmées : {total_exec} ({exec_ratio:.1f} %)")
    lines.append("")

    if stats:
        lines.append("Détails par symbole")
        for symbol, data in sorted(stats.items(), key=lambda item: item[1].get("trades", 0), reverse=True):
            trades = int(data.get("trades", 0))
            executed = int(data.get("executed", 0))
            ratio = (executed / trades * 100.0) if trades else 0.0
            rr_avg = data.get("rr_avg")
            rr_count = int(data.get("rr_count", 0))
            detail = f"- {symbol}: {executed}/{trades} exécutions ({ratio:.1f} %)"
            if rr_avg:
                detail += f", R/R moyen {rr_avg:.2f} (n={rr_count})"
            lines.append(detail)
            for key, value in sorted(data.items()):
                if key.startswith("retcode_"):
                    lines.append(f"    · {key.replace('retcode_', 'retcode ')} : {int(value)}")
        lines.append("")

    weights = tracker.snapshot(top_n=8)
    if weights:
        lines.append("Buckets les plus influents (pondérations dynamiques)")
        for row in weights:
            win_rate = row.get("win_rate")
            win_txt = "n/a" if win_rate is None else f"{float(win_rate)*100:.1f}%"
            lines.append(
                f"- {row['symbol']} | {row['agent']} | {row['bucket']}: "
                f"poids {row['weight']:.2f} (count={row['count']}, win={win_txt})"
            )
        lines.append("")

    lines.append("Notes")
    lines.append("- Exécutions basées sur retcode 10008/10009 ou flag result.ok.")
    lines.append("- R/R estimé à partir des SL/TP proposés (pas des sorties effectives).")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    files = _iter_audit_files(args.audit_dir, max(1, args.days))
    merged_records: List[Dict] = []
    for _, path in files:
        merged_records.extend(_load_records(path))
    stats = _aggregate(merged_records)
    tracker = PerformanceTracker()
    report = _build_report(args.days, stats, tracker)
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"[audit_weekly] Rapport écrit dans {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
