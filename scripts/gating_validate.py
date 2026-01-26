# scripts/gating_validate.py
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.gating import load_thresholds_for, find_latest_metrics, should_allow_trade

SYMS = ["BTCUSD","ETHUSD","LINKUSD","BNBUSD","XAUUSD","EURUSD"]
REPORT_DIR = "reports/backtests"

def main():
    any_fail = False
    for s in SYMS:
        th = load_thresholds_for(s, overrides={"min_trades": 200})
        m  = find_latest_metrics(REPORT_DIR, s)
        ok, reason, met = should_allow_trade(s, th, m)
        print(f"{s}: {'PASS' if ok else 'FAIL'} | {reason} | metrics={met}")
        any_fail |= (not ok)
    return 1 if any_fail else 0

if __name__ == "__main__":
    sys.exit(main())
