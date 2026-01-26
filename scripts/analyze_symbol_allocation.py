#!/usr/bin/env python
"""
Analyse symboles gagnants/perdants sur les 5 derniers jours pour ajuster leur poids.

Pour chaque symbole:
 - calcule le net réalisé sur 5 jours (depuis reports/ReportHistory-*.xlsx)
 - lit le PF/hit-rate via utils.live_metrics (audit_trades.jsonl)
 - si net > threshold et hit_rate > threshold, suggère de booster risk_per_trade
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from utils.live_metrics import rolling_metrics
from utils.config import get_enabled_symbols


def load_report_history(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Sheet1", header=6)
    df = df.rename(
        columns={
            "Heure": "open",
            "Heure.1": "close",
            "Symbole": "symbol",
            "Type": "type",
            "Volume": "volume",
            "Profit": "profit",
            "Commission": "commission",
            "Echange": "swap",
        }
    )
    df["close_dt"] = pd.to_datetime(df["close"], errors="coerce")
    df["net"] = (
        pd.to_numeric(df["profit"], errors="coerce")
        + pd.to_numeric(df["commission"], errors="coerce").fillna(0)
        + pd.to_numeric(df["swap"], errors="coerce").fillna(0)
    )
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df.dropna(subset=["close_dt", "net"])
    return df


def summarize_last_days(df: pd.DataFrame, days: int) -> Dict[str, Dict[str, float]]:
    if df.empty:
        return {}
    cutoff = datetime.now(df["close_dt"].dt.tz or None) - timedelta(days=days)
    recent = df[df["close_dt"] >= cutoff]
    if recent.empty:
        return {}
    summary = recent.groupby("symbol").agg(
        net=("net", "sum"),
        trades=("net", "count"),
    )
    return summary.to_dict(orient="index")


def evaluate_symbols(
    *,
    report_history: Path,
    days: int,
    net_threshold: float,
    hit_threshold: float,
    default_symbols: List[str],
) -> List[Tuple[str, Dict[str, float], Dict[str, float]]]:
    df = load_report_history(report_history)
    last_stats = summarize_last_days(df, days=days)
    suggestions: List[Tuple[str, Dict[str, float], Dict[str, float]]] = []
    for sym in default_symbols:
        metrics = rolling_metrics(sym, days=days)
        last = last_stats.get(sym, {"net": 0.0, "trades": 0.0})
        if last["net"] >= net_threshold and metrics.get("hit_rate", 0.0) >= hit_threshold:
            suggestions.append((sym, last, metrics))
    return suggestions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggère des ajustements de risque basés sur la performance récente.")
    parser.add_argument("--history", type=Path, default=Path("reports") / "ReportHistory-10960352.xlsx")
    parser.add_argument("--days", type=int, default=5, help="Fenêtre glissante en jours.")
    parser.add_argument("--net-threshold", type=float, default=300.0, help="Net minimal USD.")
    parser.add_argument("--hit-threshold", type=float, default=0.55, help="Hit-rate minimal (0-1).")
    parser.add_argument("--symbols", nargs="*", help="Liste de symboles à analyser (défaut: enabled_symbols).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols] if args.symbols else get_enabled_symbols()
    suggestions = evaluate_symbols(
        report_history=args.history,
        days=max(1, args.days),
        net_threshold=args.net_threshold,
        hit_threshold=args.hit_threshold,
        default_symbols=symbols,
    )
    if not suggestions:
        print("[allocation] Aucun symbole ne dépasse les seuils.")
        return
    print("[allocation] Symboles à renforcer :")
    for sym, last, metrics in suggestions:
        print(
            f" - {sym}: net {last['net']:.2f} USD / {last['trades']} trades | "
            f"hit={metrics.get('hit_rate', 0.0):.2%} PF={metrics.get('pf', 0.0):.2f}"
        )
        print("   Suggestion: +10% risk_per_trade ou max_trades/day sur ce symbole.")


if __name__ == "__main__":
    main()
