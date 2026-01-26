import json, yaml, pathlib, math
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = ROOT/"logs"/"audit_trades.jsonl"
PROFILES = ROOT/"config"/"profiles.yaml"

SYMBOLS = ["BTCUSD","ETHUSD","LINKUSD","BNBUSD","EURUSD","XAUUSD"]
MIN_R, MAX_R = 0.005, 0.010   # 0.5% .. 1.0%
WIN_LOOKBACK_D = 3            # fenêtre glissante 3 jours

def load_audit_since(days=WIN_LOOKBACK_D):
    if not AUDIT.exists(): return []
    ref = datetime.now(timezone.utc) - timedelta(days=days)
    out=[]
    for line in AUDIT.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = rec.get("ts")
            if not ts: continue
            t = datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)
            if t >= ref: out.append(rec)
        except: pass
    return out

def compute_kpis(recs, symbol):
    opens = [r for r in recs if r.get("symbol")==symbol and r.get("type","").upper().startswith("#NEW_TRADE")]
    closes= [r for r in recs if r.get("symbol")==symbol and r.get("type","").upper().startswith("#CLOSE_TRADE")]
    if not closes: return None
    # approx: utilise rr_realized si dispo, sinon pnl_pct/points? ici rr_realized attendu
    wins = [c for c in closes if float(c.get("rr_realized",0))>0]
    losses=[c for c in closes if float(c.get("rr_realized",0))<=0]
    pf = (sum(abs(c.get("rr_realized",0)) for c in wins) / max(1e-9, sum(abs(c.get("rr_realized",0)) for c in losses))) if losses else float('inf')
    # DD approx par cumul RR: c’est un proxy simple pour la décision
    equity=0.0; peak=0.0; dd=0.0
    for c in closes:
        equity += float(c.get("rr_realized",0))
        peak = max(peak, equity); dd = min(dd, equity-peak)
    return {"pf": pf, "dd": abs(dd)}

def main():
    recs = load_audit_since()
    if not recs: 
        print("[auto_tune] no data"); return 0

    prof = yaml.safe_load(PROFILES.read_text(encoding="utf-8"))
    profs = prof.get("profiles", {})

    changed=0
    for s in SYMBOLS:
        kpi = compute_kpis(recs, s)
        if not kpi: 
            continue
        pf, dd = kpi["pf"], kpi["dd"]
        cur = float(((profs.get(s,{}).get("risk") or {}).get("risk_per_trade", MIN_R)))
        new = cur
        # heuristique simple:
        if pf >= 1.6 and dd <= 0.06:       # très bon
            new = min(cur + 0.001, MAX_R)
        elif pf < 1.2 or dd >= 0.10:       # mauvais
            new = max(cur - 0.001, MIN_R)
        # clamp
        new = max(MIN_R, min(MAX_R, round(new,4)))
        if abs(new - cur) >= 1e-6:
            profs[s]["risk"]["risk_per_trade"] = new
            changed += 1
            print(f"[auto_tune] {s}: {cur:.4f} -> {new:.4f} (pf={pf:.2f}, dd={dd:.2f})")

    if changed:
        prof["profiles"]=profs
        PROFILES.write_text(yaml.dump(prof, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"[auto_tune] profiles.yaml updated ({changed} symbols).")
    else:
        print("[auto_tune] no changes.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
