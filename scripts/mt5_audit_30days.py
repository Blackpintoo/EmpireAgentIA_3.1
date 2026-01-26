#!/usr/bin/env python
"""Quick MT5 account audit - 30 days performance"""
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 not available")
    sys.exit(1)

# Initialize MT5
if not mt5.initialize():
    print(f"MT5 init failed: {mt5.last_error()}")
    sys.exit(1)

# Account info
account = mt5.account_info()
if account is None:
    print("Failed to get account info")
    mt5.shutdown()
    sys.exit(1)

print("=" * 60)
print("AUDIT COMPTE MT5 - 30 JOURS")
print("=" * 60)
print(f"Compte: {account.login}")
print(f"Serveur: {account.server}")
print(f"Balance: ${account.balance:,.2f}")
print(f"Equity: ${account.equity:,.2f}")
print(f"Margin: ${account.margin:,.2f}")
print(f"Free Margin: ${account.margin_free:,.2f}")
print(f"Profit flottant: ${account.profit:,.2f}")
print()

# Date range - 30 days
end_date = datetime.now(timezone.utc)
start_date = end_date - timedelta(days=30)

# Get closed deals
deals = mt5.history_deals_get(start_date, end_date)
if deals is None:
    deals = []

# Filter only closing deals (entry=1)
closed_deals = [d for d in deals if d.entry == 1 and d.profit != 0]

print(f"Periode: {start_date.strftime('%Y-%m-%d')} au {end_date.strftime('%Y-%m-%d')}")
print(f"Deals clotures: {len(closed_deals)}")
print()

total_pnl = 0
if closed_deals:
    # Calculate metrics
    profits = [d.profit for d in closed_deals]
    winners = [p for p in profits if p > 0]
    losers = [p for p in profits if p < 0]

    total_pnl = sum(profits)
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    win_rate = len(winners) / len(closed_deals) * 100 if closed_deals else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    print("PERFORMANCE 30 JOURS")
    print("-" * 40)
    print(f"Trades: {len(closed_deals)} ({len(winners)}W / {len(losers)}L)")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"P&L Net: ${total_pnl:,.2f}")
    print(f"Gain brut: ${gross_profit:,.2f}")
    print(f"Perte brute: ${gross_loss:,.2f}")
    if winners:
        print(f"Gain moyen: ${sum(winners)/len(winners):,.2f}")
    if losers:
        print(f"Perte moyenne: ${sum(losers)/len(losers):,.2f}")
    print(f"Meilleur trade: ${max(profits):,.2f}")
    print(f"Pire trade: ${min(profits):,.2f}")
    print()

    # By symbol
    by_symbol = {}
    for d in closed_deals:
        sym = d.symbol
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "pnl": 0, "wins": 0}
        by_symbol[sym]["trades"] += 1
        by_symbol[sym]["pnl"] += d.profit
        if d.profit > 0:
            by_symbol[sym]["wins"] += 1

    print("PAR SYMBOLE")
    print("-" * 40)
    print(f"{'Symbole':<12} {'Trades':>6} {'Win%':>6} {'P&L':>12}")
    for sym, data in sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        print(f"{sym:<12} {data['trades']:>6} {wr:>5.1f}% ${data['pnl']:>10,.2f}")
    print()

# Open positions
positions = mt5.positions_get()
if positions:
    print("POSITIONS OUVERTES")
    print("-" * 40)
    total_floating = 0
    for pos in positions:
        direction = "BUY" if pos.type == 0 else "SELL"
        print(f"#{pos.ticket} {pos.symbol} {direction} {pos.volume} lots @ {pos.price_open:.5f} P&L: ${pos.profit:,.2f}")
        total_floating += pos.profit
    print(f"\nTotal flottant: ${total_floating:,.2f}")
else:
    print("Aucune position ouverte")

print()

# Objectif mensuel
monthly_target = 5555
progress = (total_pnl / monthly_target * 100) if closed_deals else 0
print("OBJECTIF MENSUEL")
print("-" * 40)
print(f"Cible: ${monthly_target:,.2f}/mois")
print(f"Realise: ${total_pnl:,.2f}")
print(f"Progression: {progress:.1f}%")

if total_pnl >= monthly_target:
    print("STATUS: OBJECTIF ATTEINT!")
elif total_pnl > 0:
    remaining = monthly_target - total_pnl
    print(f"Reste a faire: ${remaining:,.2f}")
else:
    print(f"STATUS: EN DEFICIT de ${abs(total_pnl):,.2f}")

print("=" * 60)

mt5.shutdown()
