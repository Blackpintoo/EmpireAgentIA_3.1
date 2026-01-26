#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Europe/Zurich")


def clean_volume(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.split('/').str[0].str.strip(), errors='coerce')


def load_closed(history_path: Path) -> pd.DataFrame:
    df = pd.read_excel(history_path, sheet_name="Sheet1", header=6)
    df = df.rename(columns={'Heure.1': 'Heure_close', 'Prix.1': 'Prix_close', 'Unnamed: 13': 'Commentaire'})
    dt = pd.to_datetime(df['Heure'], errors='coerce')
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize(TZ, nonexistent='shift_forward', ambiguous='NaT')
    else:
        dt = dt.dt.tz_convert(TZ)
    df['Heure_dt'] = dt
    df['Profit'] = pd.to_numeric(df['Profit'], errors='coerce')
    df['Commission'] = pd.to_numeric(df['Commission'], errors='coerce')
    df['Echange'] = pd.to_numeric(df['Echange'], errors='coerce')
    df['Volume'] = clean_volume(df['Volume'])
    df = df.dropna(subset=['Heure_dt', 'Profit', 'Volume'])
    df = df[df['Type'].str.lower().isin(['buy', 'sell'])]
    df['net_profit'] = df['Profit'] + df['Commission'].fillna(0) + df['Echange'].fillna(0)
    return df


def today_range(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end




def log_guard_event(tag: str, message: str) -> None:
    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(TZ).isoformat()
        entry = f"{ts}|GLOBAL|{tag}|{message}\n"
        with (logs_dir / "guards.log").open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass
def ensure_guard_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_flag(path: Path, message: str) -> None:
    path.write_text(message + "\n", encoding="utf-8")


def remove_flag(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Garde journalière: stop loss / take profit global.")
    parser.add_argument("--history", default="reports/ReportHistory-10960352.xlsx", help="Fichier historique MT5")
    parser.add_argument("--target", type=float, default=167.0, help="Objectif net journalier en USD")
    parser.add_argument("--stop", type=float, default=-250.0, help="Seuil net à partir duquel on stoppe (valeur négative)")
    parser.add_argument("--guards-dir", default="data/guards", help="Répertoire des flags")
    args = parser.parse_args()

    history_path = Path(args.history)
    if not history_path.exists():
        raise SystemExit(f"Historique introuvable: {history_path}")

    df = load_closed(history_path)
    now = datetime.now(TZ)
    start, end = today_range(now)
    today_df = df[(df['Heure_dt'] >= start) & (df['Heure_dt'] <= end)]
    net_today = float(today_df['net_profit'].sum()) if not today_df.empty else 0.0
    trades_today = int(len(today_df))

    guards_dir = ensure_guard_dir(Path(args.guards_dir))
    stop_flag = guards_dir / "stop_all.flag"
    target_flag = guards_dir / "target_met.flag"

    did_stop = False
    did_target = False

    if net_today <= args.stop:
        message = (f"STOP {now:%Y-%m-%d}: net={net_today:.2f} <= {args.stop:.2f} | trades={trades_today}")
        write_flag(stop_flag, message)
        log_guard_event("daily-stop", message)
        did_stop = True
    else:
        remove_flag(stop_flag)

    if net_today >= args.target:
        message = (f"TARGET {now:%Y-%m-%d}: net={net_today:.2f} >= {args.target:.2f} | trades={trades_today}")
        write_flag(target_flag, message)
        log_guard_event("daily-target", message)
        did_target = True
    else:
        remove_flag(target_flag)

    print(f"Net today: {net_today:.2f} USD ({trades_today} trades)")
    print(f"Stop guard active: {did_stop}")
    print(f"Target guard active: {did_target}")


if __name__ == "__main__":
    main()
