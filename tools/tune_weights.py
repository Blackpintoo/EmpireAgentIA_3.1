# tools/tune_weights.py
import yaml, json, pandas as pd, numpy as np

CFG = "config/profiles.yaml"

def ewma(x, alpha=0.2):
    return x.ewm(alpha=alpha, adjust=False).mean()

def compute_agent_scores(proposals_csv, trades_csv):
    P = pd.read_csv(proposals_csv, parse_dates=["ts_utc"])
    T = pd.read_csv(trades_csv, parse_dates=["ts_utc"])
    # On suppose qu’un trade “match” la proposition la plus proche dans le temps même symbole/direction
    P["key"] = P["symbol"] + "|" + P["side"]
    T["key"] = T["symbol"] + "|" + T["side"]

    # merge nearest (simpliste)
    P = P.sort_values("ts_utc")
    T = T.sort_values("ts_utc")
    merged = pd.merge_asof(T, P, on="ts_utc", by="key", tolerance=pd.Timedelta("10m"), direction="backward")

    # outcome: ok=1 si retcode=10009 (exécuté) et résultat positif (si tu logues PnL, sinon placeholder)
    merged["ok_exec"] = (merged["retcode"]==10009).astype(int)
    # TODO: si tu logues PnL: merged["win"] = (merged["pnl"]>0).astype(int)
    merged["win"] = merged["ok_exec"]  # approximation sans PnL

    # exemples de colonnes agent_* dans proposals_log.csv (à ajouter côté orch)
    agent_cols = [c for c in merged.columns if c.startswith("agent_")]  # p.ex. agent_technical, agent_news...
    scores = {}
    for col in agent_cols:
        # score = EWMA de la winrate quand l’agent a voté dans le sens final
        m = merged[merged[col].notna()]
        if len(m) < 30:
            continue
        scores[col] = float(ewma(m["win"]).iloc[-1])
    return scores

def main():
    scores = compute_agent_scores("data/proposals_log.csv", "data/trades_log.csv")
    if not scores:
        print("No scores yet."); return

    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    for sym, prof in (cfg.get("symbols") or {}).items():
        w = ((prof.get("orchestrator") or {}).get("agent_weights") or {})
        # pas plus de ±0.05 par itération
        for k in ("news","swing","scalping"):
            key = f"agent_{k}"
            if key in scores:
                delta = (scores[key] - 0.5) * 0.1  # centrage 0.5
                w[k] = float(np.clip(w.get(k, 0.5) + delta, 0.1, 1.5))
        prof.setdefault("orchestrator", {})["agent_weights"] = w

    yaml.safe_dump(cfg, open(CFG, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    print("weights updated:", scores)

if __name__ == "__main__":
    main()
