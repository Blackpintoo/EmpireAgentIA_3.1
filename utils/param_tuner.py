# utils/param_tuner.py
import os, csv, math
from collections import defaultdict
import yaml

DATA = os.path.join("data", "deals_history.csv")
OUT_DIR = "proposals"
OUT = os.path.join(OUT_DIR, "profiles_patch.yaml")

def load_deals():
    if not os.path.exists(DATA):
        return []
    rows = []
    with open(DATA, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                row["profit"] = float(row.get("profit", 0) or 0)
                rows.append(row)
            except Exception:
                pass
    return rows

def rolling_winrate(rows, sym, k=100):
    vals = [1 if r["profit"]>0 else 0 for r in rows if r.get("symbol")==sym]
    vals = vals[-k:] if len(vals)>k else vals
    if not vals: return None
    return sum(vals)/len(vals)

def main():
    rows = load_deals()
    if not rows:
        print("No deals -> no patch.")
        return
    os.makedirs(OUT_DIR, exist_ok=True)

    symbols = sorted({r["symbol"] for r in rows if r.get("symbol")})
    patch = {"profiles": {}}

    for sym in symbols:
        wr = rolling_winrate(rows, sym, k=150)  # winrate récent
        if wr is None: 
            continue

        # Propositions très conservatrices
        o = {}
        if wr < 0.40:
            o["min_score_for_proposal"] = 2.0
            o["atr_sl_mult"] = 1.7
            o["atr_tp_mult"] = 2.2
            o["votes_required"] = 2
        elif wr < 0.50:
            o["min_score_for_proposal"] = 1.9
            o["atr_sl_mult"] = 1.6
            o["atr_tp_mult"] = 2.3
            o["votes_required"] = 2
        else:
            o["min_score_for_proposal"] = 1.8
            o["atr_sl_mult"] = 1.5
            o["atr_tp_mult"] = 2.5
            o["votes_required"] = 1

        patch["profiles"].setdefault(sym, {})["orchestrator"] = o

    with open(OUT, "w", encoding="utf-8") as f:
        yaml.safe_dump(patch, f, allow_unicode=True, sort_keys=False)
    print(f"Wrote {OUT}")

if __name__ == "__main__":
    main()
