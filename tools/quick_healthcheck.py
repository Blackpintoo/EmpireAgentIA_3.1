import csv, os, statistics as st
from collections import defaultdict, Counter
from datetime import datetime

path = os.path.join("data", "trades_log.csv")
rows = []
with open(path, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            r["ts"] = datetime.fromisoformat(r.get("ts_utc","").replace("Z",""))
        except Exception:
            r["ts"] = None
        r["ok"] = str(r.get("ok","")).lower() in ("true","1","yes")
        r["symbol"] = (r.get("symbol","") or "").upper()
        rows.append(r)

by_sym = defaultdict(list)
for r in rows:
    by_sym[r["symbol"]].append(r)

def streaks(seq):
    # calcule streaks de pertes consécutives
    cur = best = 0
    for v in seq:
        if v is False:
            cur += 1; best = max(best, cur)
        else:
            cur = 0
    return best

print("=== Résumé global ===")
print(f"Trades totaux: {len(rows)}")
wins = sum(1 for r in rows if r["ok"])
print(f"Win rate global: {wins/len(rows)*100:.1f}%\n" if rows else "n/a\n")

for sym, lst in by_sym.items():
    wins = sum(1 for r in lst if r["ok"])
    wr = wins/len(lst)*100 if lst else 0.0
    loss_seq = [r["ok"] for r in lst]
    max_losing_streak = streaks(loss_seq)
    # distribution par heure locale (si ts présent)
    hours = Counter((r["ts"].hour if r["ts"] else None) for r in lst)
    print(f"[{sym}] trades={len(lst)} | winrate={wr:.1f}% | max losing streak={max_losing_streak}")
