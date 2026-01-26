#!/usr/bin/env python
"""
Daily performance consolidator.

Reads the MT5 exports:
 - ReportHistory-*.xlsx  (closed trades)
 - ReportTrade-*.xlsx    (open positions)

Outputs a daily summary with realized PnL, swaps, commissions,
floating PnL and basic risk metrics.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


HISTORY_PATTERN = "ReportHistory-*.xlsx"
TRADE_PATTERN = "ReportTrade-*.xlsx"


def _latest(path: Path, pattern: str) -> Path:
    files = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"Aucun fichier trouvé pour {pattern} dans {path}")
    return files[0]


def _clean_volume(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.split("/").str[0].str.strip(), errors="coerce")


def _load_closed(history_path: Path) -> pd.DataFrame:
    df = pd.read_excel(history_path, sheet_name="Sheet1", header=6)
    df = df.rename(
        columns={
            "Heure.1": "Heure_close",
            "Prix.1": "Prix_close",
            "Unnamed: 13": "Commentaire",
        }
    )
    df["Heure_dt"] = pd.to_datetime(df["Heure"], errors="coerce")
    df["Close_dt"] = pd.to_datetime(df["Heure_close"], errors="coerce")
    numeric_cols = [
        "Volume",
        "Prix",
        "S / L",
        "T / P",
        "Prix_close",
        "Commission",
        "Echange",
        "Profit",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = _clean_volume(df["Volume"])
    df = df[df["Volume"].notna()]
    df = df[df["Type"].astype(str).str.lower().isin({"buy", "sell"})]
    closed = df.dropna(subset=["Heure_dt", "Profit"]).copy()
    closed["net_profit"] = closed["Profit"] + closed["Commission"].fillna(0) + closed["Echange"].fillna(0)
    return closed


def _load_open(trade_path: Path) -> pd.DataFrame:
    df = pd.read_excel(trade_path, sheet_name="Sheet1", header=6)
    df.columns = (
        df.columns.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
    )
    df["Heure_dt"] = pd.to_datetime(df["Heure"], errors="coerce")

    numeric_cols = ["Prix", "S / L", "T / P", "Prix du marche", "Echange", "Profit"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = _clean_volume(df["Volume"])
    open_positions = df.dropna(subset=["Heure_dt", "Symbole"]).copy()
    open_positions["net_profit"] = open_positions["Profit"].fillna(0) + open_positions["Echange"].fillna(0)
    return open_positions


@dataclass
class DailyReport:
    closed: pd.DataFrame
    open_positions: pd.DataFrame
    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]

    def filter_period(self) -> None:
        if self.start:
            self.closed = self.closed[self.closed["Heure_dt"] >= self.start]
        if self.end:
            self.closed = self.closed[self.closed["Heure_dt"] <= self.end]

    def realized_summary(self) -> pd.DataFrame:
        if self.closed.empty:
            return pd.DataFrame(columns=["date", "trades", "realized", "swap", "commission", "net", "win_rate"])
        daily = (
            self.closed.assign(date=self.closed["Close_dt"].dt.date)
            .groupby("date")
            .agg(
                trades=("Profit", "count"),
                realized=("Profit", "sum"),
                swap=("Echange", "sum"),
                commission=("Commission", "sum"),
                net=("net_profit", "sum"),
                win_rate=("Profit", lambda s: (s > 0).mean() if len(s) else 0.0),
            )
            .reset_index()
            .sort_values("date")
        )
        return daily

    def realized_totals(self) -> dict:
        return {
            "trades": int(len(self.closed)),
            "realized_profit": float(self.closed["Profit"].sum()),
            "swap": float(self.closed["Echange"].sum()),
            "commission": float(self.closed["Commission"].sum()),
            "net_profit": float(self.closed["net_profit"].sum()),
            "win_rate": float((self.closed["Profit"] > 0).mean()) if not self.closed.empty else 0.0,
        }

    def floating_summary(self) -> Tuple[pd.DataFrame, dict]:
        if self.open_positions.empty:
            return pd.DataFrame(columns=["Symbole", "positions", "volume", "floating", "swap", "net"]), {
                "positions": 0,
                "volume": 0.0,
                "floating": 0.0,
                "swap": 0.0,
                "net": 0.0,
            }
        by_symbol = (
            self.open_positions.groupby("Symbole")
            .agg(
                positions=("Symbole", "count"),
                volume=("Volume", "sum"),
                floating=("Profit", "sum"),
                swap=("Echange", "sum"),
                net=("net_profit", "sum"),
            )
            .sort_values("net", ascending=False)
            .reset_index()
        )
        totals = {
            "positions": int(self.open_positions["Symbole"].count()),
            "volume": float(self.open_positions["Volume"].sum(skipna=True)),
            "floating": float(self.open_positions["Profit"].sum(skipna=True)),
            "swap": float(self.open_positions["Echange"].sum(skipna=True)),
            "net": float(self.open_positions["net_profit"].sum(skipna=True)),
        }
        return by_symbol, totals


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suivi quotidien des performances (réalisées + flottantes).")
    parser.add_argument("--reports-dir", default="reports", help="Dossier contenant les exports MT5.")
    parser.add_argument("--history", help="Chemin spécifique vers ReportHistory-*.xlsx.")
    parser.add_argument("--trades", help="Chemin spécifique vers ReportTrade-*.xlsx.")
    parser.add_argument("--start", help="Date de début (YYYY-MM-DD).")
    parser.add_argument("--end", help="Date de fin (YYYY-MM-DD).")
    parser.add_argument("--days", type=int, help="Nombre de jours récents à analyser (prioritaire sur --start).")
    parser.add_argument("--export-dir", help="Dossier où stocker les CSV/texte du rapport (créera un sous-dossier horodaté).")
    return parser.parse_args()


def _determine_period(args: argparse.Namespace) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    end = None
    if args.end:
        end = pd.to_datetime(args.end)
    if args.days:
        end = end or pd.Timestamp.now()
        start = end - timedelta(days=args.days - 1)
        return start.normalize(), end
    start = pd.to_datetime(args.start) if args.start else None
    return start, end


def main() -> None:
    args = _parse_args()
    reports_dir = Path(args.reports_dir)
    hist_path = Path(args.history) if args.history else _latest(reports_dir, HISTORY_PATTERN)
    trade_path = Path(args.trades) if args.trades else _latest(reports_dir, TRADE_PATTERN)

    closed = _load_closed(hist_path)
    open_positions = _load_open(trade_path)
    start, end = _determine_period(args)

    rpt = DailyReport(closed=closed, open_positions=open_positions, start=start, end=end)
    rpt.filter_period()

    daily = rpt.realized_summary()
    totals = rpt.realized_totals()
    floating_by_symbol, floating_totals = rpt.floating_summary()

    print("=== Suivi quotidien réalisé ===")
    if daily.empty:
        print("Aucun trade clôturé dans la période.")
    else:
        print(daily.to_string(index=False, formatters={"win_rate": "{:.2%}".format}))

    print("\nTotaux période:")
    print(
        f"- Trades clôturés: {totals['trades']}\n"
        f"- Profit réalisé: {totals['realized_profit']:.2f}\n"
        f"- Swap: {totals['swap']:.2f}\n"
        f"- Commissions: {totals['commission']:.2f}\n"
        f"- Net réalisé: {totals['net_profit']:.2f}\n"
        f"- Taux de réussite: {totals['win_rate']:.2%}"
    )

    print("\n=== Exposition flottante actuelle ===")
    print(f"Positions ouvertes: {floating_totals['positions']} | Volume total: {floating_totals['volume']:.2f} lots")
    print(f"P&L flottant: {floating_totals['floating']:.2f} | Swap: {floating_totals['swap']:.2f} | Net: {floating_totals['net']:.2f}")

    if not floating_by_symbol.empty:
        print("\nDétail par symbole (flottant):")
        print(floating_by_symbol.to_string(index=False))

    print("\nFichiers utilisés:")
    print(f"- Historique : {hist_path}")
    print(f"- Positions  : {trade_path}")

    if args.export_dir:
        export_root = Path(args.export_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = export_root / f"daily_report_{timestamp}"
        export_path.mkdir(parents=True, exist_ok=True)

        daily.to_csv(export_path / "daily_realized.csv", index=False)
        floating_by_symbol.to_csv(export_path / "floating_by_symbol.csv", index=False)

        summary_lines = [
            "# Résumé performance quotidienne",
            f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "## Période analysée",
            f"- Début: {start.date() if start else 'N/A'}",
            f"- Fin: {end.date() if end else 'N/A'}",
            "",
            "## Totaux réalisés",
            f"- Trades clôturés: {totals['trades']}",
            f"- Profit réalisé: {totals['realized_profit']:.2f}",
            f"- Swap: {totals['swap']:.2f}",
            f"- Commissions: {totals['commission']:.2f}",
            f"- Net réalisé: {totals['net_profit']:.2f}",
            f"- Taux de réussite: {totals['win_rate']:.2%}",
            "",
            "## Exposition flottante",
            f"- Positions ouvertes: {floating_totals['positions']}",
            f"- Volume total: {floating_totals['volume']:.2f} lots",
            f"- PnL flottant: {floating_totals['floating']:.2f}",
            f"- Swap: {floating_totals['swap']:.2f}",
            f"- Net flottant: {floating_totals['net']:.2f}",
            "",
            "## Sources",
            f"- Historique: {hist_path}",
            f"- Positions : {trade_path}",
        ]
        (export_path / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
        print(f"\nExports écrits dans {export_path}")


if __name__ == "__main__":
    main()
