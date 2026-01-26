"""Agent signal reporting utility.

Examples:
    python -m scripts.agent_signal_report --days 3
    python -m scripts.agent_signal_report --start 2025-09-01 --end 2025-09-05 --symbols BTCUSD ETHUSD
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

DATE_FMT = "%Y-%m-%d"
TS_KEY = "ts_utc"
BASE_DIR = Path(__file__).resolve().parents[1]
AGENT_LOG = BASE_DIR / "data" / "agents_snap.jsonl"


@dataclass
class SignalStats:
    counts: Dict[str, Dict[str, int]]

    def __init__(self) -> None:
        self.counts = defaultdict(lambda: defaultdict(int))

    def update(self, agent: str, timeframe: str, signal: Optional[str]) -> None:
        key = signal or "NONE"
        self.counts[agent][f"{timeframe}:{key}"] += 1

    def summarise(self) -> Dict[str, Dict[str, int]]:
        return {agent: dict(tf_counts) for agent, tf_counts in self.counts.items()}


@dataclass
class EquityStats:
    min_equity: Optional[float] = None
    max_equity: Optional[float] = None

    def update(self, val: Optional[float]) -> None:
        if val is None:
            return
        if self.min_equity is None or val < self.min_equity:
            self.min_equity = val
        if self.max_equity is None or val > self.max_equity:
            self.max_equity = val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyse des signaux agents (agents_snap.jsonl)")
    parser.add_argument("--start", type=str, help="Date début YYYY-MM-DD (inclusif)")
    parser.add_argument("--end", type=str, help="Date fin YYYY-MM-DD (exclusif)")
    parser.add_argument("--days", type=int, help="Alternative start/end : N jours en arrière", default=None)
    parser.add_argument("--symbols", nargs="*", help="Filtrer certains symboles")
    parser.add_argument("--contexts", nargs="*", help="Filtre contexts (executed/proposed/...)")
    return parser.parse_args()


def parse_range(args: argparse.Namespace) -> (datetime, datetime):
    if args.start and args.end:
        start = datetime.strptime(args.start, DATE_FMT).replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end, DATE_FMT).replace(tzinfo=timezone.utc)
    else:
        days = args.days or 7
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
    if end <= start:
        raise ValueError("end doit être après start")
    return start, end


def normalise_signal(sig: Optional[str]) -> Optional[str]:
    if not sig:
        return None
    val = str(sig).strip().upper()
    if val in {"LONG", "SHORT", "WAIT", "BUY", "SELL"}:
        mapping = {"BUY": "LONG", "SELL": "SHORT"}
        return mapping.get(val, val)
    return val


def process_file(start: datetime, end: datetime, symbols: Optional[Iterable[str]], contexts: Optional[Iterable[str]]) -> Dict[str, Dict[str, int]]:
    stats = SignalStats()
    equity_stats = EquityStats()

    if not AGENT_LOG.exists():
        print("Aucun fichier agents_snap.jsonl détecté.")
        return {}

    sym_set = set(s.upper() for s in symbols) if symbols else None
    ctx_set = set(c.lower() for c in contexts) if contexts else None

    with AGENT_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_raw = rec.get(TS_KEY)
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < start or ts >= end:
                continue

            symbol = (rec.get("symbol") or "").upper()
            if sym_set and symbol not in sym_set:
                continue

            ctx = str(rec.get("context", "")).lower()
            if ctx_set and ctx not in ctx_set:
                continue

            per_tf = rec.get("per_tf_signals") or {}
            for agent, mapping in per_tf.items():
                if not isinstance(mapping, dict):
                    continue
                for timeframe, raw_sig in mapping.items():
                    stats.update(agent, timeframe.upper(), normalise_signal(raw_sig))

            global_signals = rec.get("global_signals") or {}
            for agent, raw_sig in global_signals.items():
                stats.update(agent, "GLOBAL", normalise_signal(raw_sig))

            market = rec.get("market") or {}
            try:
                eq = float(market.get("equity")) if market.get("equity") is not None else None
            except (TypeError, ValueError):
                eq = None
            equity_stats.update(eq)

    summary = stats.summarise()
    print_summary(summary)
    if equity_stats.min_equity is not None and equity_stats.max_equity is not None:
        delta = equity_stats.max_equity - equity_stats.min_equity
        pct = (delta / equity_stats.min_equity * 100.0) if equity_stats.min_equity else 0.0
        print()
        print(f"Équity min: {equity_stats.min_equity:.2f} | Équity max: {equity_stats.max_equity:.2f} | Δ={delta:.2f} ({pct:.2f}%)")
    return summary


def print_summary(summary: Dict[str, Dict[str, int]]) -> None:
    if not summary:
        print("Aucune donnée dans la plage sélectionnée.")
        return

    for agent, counts in sorted(summary.items()):
        total = sum(counts.values())
        print(f"=== {agent.upper()} (total={total}) ===")
        for key, value in sorted(counts.items(), key=lambda kv: kv[0]):
            timeframe, signal = key.split(":", 1)
            pct = value / total * 100 if total else 0
            print(f"  {timeframe:<6} {signal:<6} : {value:>5} ({pct:5.1f}%)")
        print()


def main() -> None:
    args = parse_args()
    start, end = parse_range(args)
    process_file(start, end, args.symbols, args.contexts)


if __name__ == "__main__":
    main()
