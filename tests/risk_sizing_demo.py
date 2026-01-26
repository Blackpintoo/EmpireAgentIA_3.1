# tests/risk_sizing_demo.py
from __future__ import annotations
import os, sys, math
from typing import Optional

# Permet d'exécuter le script depuis n'importe où
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.risk_manager import RiskManager  # utilise tes patchs
from utils.config import get_symbol_profile, load_config

def fmt(v: Optional[float], nd=3):
    if v is None: return "None"
    if isinstance(v, (int, float)):
        return f"{v:.{nd}f}"
    return str(v)

def print_header(title: str):
    print("\n" + "="*80)
    print(title)
    print("="*80)

def demo_symbol(symbol: str, stops_points=(30, 80, 150)):
    rm = RiskManager(symbol)
    cfg = load_config() or {}
    prof = get_symbol_profile(symbol) or {}
    inst = prof.get("instrument", {}) if isinstance(prof, dict) else {}
    point = float(inst.get("point", 0.01) or 0.01)
    pipval = float(inst.get("pip_value", 1.0) or 1.0)

    eq = rm.get_equity()
    print_header(f"[{symbol}] Instrument: point={point} | pip_value={pipval} | equity={fmt(eq,2)}")
    print("Broker costs (config.yaml):", {
        "commission_per_lot": cfg.get("broker_costs", {}).get("commission_per_lot"),
        "spread_points": cfg.get("broker_costs", {}).get("spread_points"),
        "slippage_entry": cfg.get("broker_costs", {}).get("slippage_points_entry"),
        "slippage_exit": cfg.get("broker_costs", {}).get("slippage_points_exit"),
    })

    for sp in stops_points:
        lots = rm.compute_position_size(eq, stop_distance_points=sp)
        print(f"- Stop distance = {sp:>4} pts -> lots = {fmt(lots)}")

    # Test guard daily loss (simulé)
    print_header(f"[{symbol}] Simu daily loss guard")
    for dl_ratio in (0.0, -0.005, -0.01, -0.015, -0.02, -0.03):  # 0% -1% -2% -3%
        stop = rm.is_daily_limit_reached(daily_loss_pct=dl_ratio, consec_losses=0)
        lots = rm.compute_position_size(eq, stop_distance_points=80)
        print(f"daily_loss={dl_ratio:.2%} -> stop={stop} | risk_scale_applied -> lots={fmt(lots)}")

    # Test streak guard
    print_header(f"[{symbol}] Simu losing streak")
    for streak in (0, 1, 2, 3, 4):
        stop = rm.is_daily_limit_reached(daily_loss_pct=-0.003, consec_losses=streak)
        lots = rm.compute_position_size(eq, stop_distance_points=80)
        print(f"streak={streak} -> stop={stop} | lots={fmt(lots)}")

def main():
    # Choisis les symboles que tu utilises réellement (et présents dans profiles.yaml)
    symbols = ["EURUSD", "BTCUSD", "XAUUSD", "LINKUSD"]
    for s in symbols:
        try:
            demo_symbol(s)
        except Exception as e:
            print_header(f"[{s}] ERREUR")
            print(e)

if __name__ == "__main__":
    main()
