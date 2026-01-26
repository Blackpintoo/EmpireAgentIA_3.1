"""
Mock backfill for whale copy-trading events.

Usage:
    python scripts/backfill_whales.py --days 7 --rows 2000

Writes a SQLite database (store/whales.db) with table `whale_trades`
containing synthetic whale trades that can be consumed by the agent/dashboard.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pandas as pd

SYMBOLS = ["BTCUSD", "ETHUSD", "LINKUSD", "BNBUSD", "SOLUSD"]
SIDES = ["LONG", "SHORT"]


def generate_rows(days: int, rows: int) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    entries: List[dict] = []
    for _ in range(rows):
        age = random.random() * days
        ts = now - timedelta(days=age, minutes=random.randint(0, 60), seconds=random.randint(0, 59))
        wallet = f"0x{random.getrandbits(160):040x}"
        symbol = random.choice(SYMBOLS)
        side = random.choice(SIDES)
        price = round(random.uniform(15, 25000), 2)
        volume = random.uniform(50_000, 5_000_000)
        trust_score = max(0.0, min(1.0, random.gauss(0.65, 0.15)))
        signal_score = max(0.0, min(1.0, random.gauss(0.6, 0.2)))
        pnl = random.uniform(-0.05, 0.08) * volume / price
        latency_ms = random.uniform(100, 5000)
        entries.append(
            {
                "ts": ts.isoformat(),
                "wallet": wallet,
                "symbol": symbol,
                "side": side,
                "price": price,
                "volume_usd": volume,
                "trust_score": trust_score,
                "signal_score": signal_score,
                "pnl_usd": pnl,
                "latency_ms": latency_ms,
            }
        )
    return pd.DataFrame(entries)


def main() -> None:
    parser = argparse.ArgumentParser("Backfill whale trades (synthetic)")
    parser.add_argument("--days", type=int, default=7, help="Lookback days to simulate")
    parser.add_argument("--rows", type=int, default=1000, help="Number of rows to generate")
    parser.add_argument("--output", default="store/whales.db", help="SQLite output file")
    args = parser.parse_args()

    df = generate_rows(days=max(1, args.days), rows=max(10, args.rows))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(output_path) as conn:
        df.to_sql("whale_trades", conn, if_exists="replace", index=False)

    print(f"[backfill_whales] Wrote {len(df)} rows to {output_path} (table whale_trades)")


if __name__ == "__main__":
    main()
