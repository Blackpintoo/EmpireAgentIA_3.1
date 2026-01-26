# utils/analyze_trades.py
import os, csv, math
from datetime import datetime

DEALS = os.path.join("data","deals_history.csv")

def _read_deals(path):
    rows=[]
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                row["time"] = int(row.get("time", 0) or 0)
                row["profit"] = float(row.get("profit", 0) or 0)
                row["commission"] = float(row.get("commission", 0) or 0)
                row["swap"] = float(row.get("swap", 0) or 0)
                row["symbol"] = (row.get("symbol") or "").upper()
                row["net"] = row["profit"] - abs(row["commission"]) + row["swap"]
                rows.append(row)
            except Exception:
                pass
    return rows

def _dd(series):
    peak = -10**18
    dd_max = 0.0
    cur = 0.0
    for x in series:
        cur += x
        peak = max(peak, cur)
        dd = peak - cur
        if dd > dd_max:
            dd_max = dd
    return dd_max, cur  # maxDD, cum

def summarize(rows):
    if not rows:
        print("[ANALYZE] Aucune donnée. Lance d’abord: python utils/sync_history.py")
        return
    by_sym = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)

    def stats(sym, arr):
        net = [x["net"] for x in arr if abs(x["net"])>0 or True]
        wins = [x for x in net if x>0]
        losses = [x for x in net if x<0]
        wr = (len(wins)/len(net))*100 if net else 0.0
        pf = (sum(wins)/abs(sum(losses))) if losses else float('inf') if wins else 0.0
        exp = (sum(wins)/len(net) if net else 0.0) - (abs(sum(losses))/len(net) if net else 0.0)
        dd, cum = _dd(net)
        return {
            "trades": len(net),
            "winrate_%": wr,
            "profit_factor": pf,
            "expectancy": exp,
            "net_total": sum(net),
            "max_drawdown": dd,
            "cum_pnl": cum,
            "avg_win": (sum(wins)/len(wins) if wins else 0.0),
            "avg_loss": (sum(losses)/len(losses) if losses else 0.0),
        }

    all_rows = [x for x in rows]
    print("\n=== PERFORMANCE GLOBALE ===")
    s = stats("ALL", all_rows)
    for k,v in s.items():
        print(f"{k:16s}: {v}")

    print("\n=== PAR SYMBOLE ===")
    for sym, arr in sorted(by_sym.items()):
        s = stats(sym, arr)
        print(f"\n[{sym}]")
        for k,v in s.items():
            print(f"{k:16s}: {v}")

if __name__ == "__main__":
    rows = _read_deals(DEALS)
    summarize(rows)
