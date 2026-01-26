# scripts/metrics_from_audit.py
import json, argparse, pathlib, sys, math
from datetime import datetime, timezone
from collections import defaultdict

def to_dt(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def parse_args():
    ap = argparse.ArgumentParser("metrics_from_audit")
    ap.add_argument("--file", default="logs/audit_trades.jsonl", help="Chemin du fichier audit JSONL")
    ap.add_argument("--since", default=None, help="Filtre date UTC incluse (YYYY-MM-DD)")
    ap.add_argument("--symbol", default=None, help="Filtrer un symbole (ex: BTCUSD)")
    return ap.parse_args()

def main():
    args = parse_args()
    p = pathlib.Path(args.file)
    if not p.exists():
        print(f"❌ Fichier introuvable: {p}")
        return 2

    since_dt = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except Exception:
            print("⚠️ --since invalide; format attendu YYYY-MM-DD (ex: 2025-09-01)")
            since_dt = None

    opens = []   # enregistrements #NEW_TRADE*
    closes = []  # enregistrements #CLOSE_TRADE*
    raw = []

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            raw.append(rec)

    # Filtrage
    filt = []
    for r in raw:
        ts = r.get("ts")
        dt = to_dt(ts) if ts else None
        if since_dt and dt and dt < since_dt:
            continue
        if args.symbol and r.get("symbol") != args.symbol:
            continue
        filt.append(r)

    # Séparer opens/closes
    for r in filt:
        t = str(r.get("type","")).upper()
        if t.startswith("#NEW_TRADE"):
            opens.append(r)
        elif t.startswith("#CLOSE_TRADE"):
            closes.append(r)

    # Construction des "trades clos" exploitable pour métriques
    # Hypothèse: en close on essaie de lire rr réalisé (rr_realized | rr | pnl_rr)
    # et risk_pct (sinon on essaie de retrouver depuis un open précédent du même symbole)
    # Si on ne trouve rien => on ignore pour PF/expectancy, mais on garde le comptage.
    equity_points = []  # (dt, equity)
    equity = 1.0

    wins = 0
    losses = 0
    rr_win_sum = 0.0
    rr_loss_sum = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    n_closes_used = 0

    # index simple des derniers opens par symbole pour récupérer risk_pct par défaut
    last_open_risk_by_symbol = {}
    for o in opens:
        sym = o.get("symbol")
        rp = o.get("risk_pct")
        if sym and isinstance(rp, (int,float)):
            last_open_risk_by_symbol[sym] = float(rp)

    per_day = defaultdict(lambda: dict(n_open=0, n_close=0, rr_win=0.0, rr_loss=0.0,
                                       wins=0, losses=0, gross_profit=0.0, gross_loss=0.0))

    for o in opens:
        dt = to_dt(o.get("ts") or "")
        day = dt.date().isoformat() if dt else "unknown"
        per_day[day]["n_open"] += 1

    for c in closes:
        dt = to_dt(c.get("ts") or "")
        day = dt.date().isoformat() if dt else "unknown"
        per_day[day]["n_close"] += 1

        rr = None
        for key in ("rr_realized","rr","pnl_rr","rr_result","r_multiple"):
            v = c.get(key)
            if isinstance(v,(int,float)):
                rr = float(v)
                break
        if rr is None:
            # parfois PnL en %:
            pnl_pct = c.get("pnl_pct")
            if isinstance(pnl_pct,(int,float)):
                # approx: r-multiple = pnl_pct / risk_pct
                risk_pct = c.get("risk_pct")
                if not isinstance(risk_pct,(int,float)):
                    risk_pct = last_open_risk_by_symbol.get(c.get("symbol"), 0.005)
                if risk_pct:
                    rr = float(pnl_pct)/float(risk_pct)

        if rr is None:
            continue  # pas exploitable pour métriques R

        # risk_pct: de la ligne close sinon du dernier open de ce symbole
        risk_pct = c.get("risk_pct")
        if not isinstance(risk_pct,(int,float)):
            risk_pct = last_open_risk_by_symbol.get(c.get("symbol"), 0.005)
        risk_pct = float(risk_pct)

        # mise à jour courbe d'équité (équity en "unités" où 1.0 = 100%)
        delta = risk_pct * rr
        equity += delta
        if dt:
            equity_points.append((dt, equity))

        n_closes_used += 1
        if rr > 0:
            wins += 1
            rr_win_sum += rr
            gross_profit += delta
            per_day[day]["wins"] += 1
            per_day[day]["rr_win"] += rr
            per_day[day]["gross_profit"] += delta
        else:
            losses += 1
            rr_loss_sum += abs(rr)
            gross_loss += abs(delta)
            per_day[day]["losses"] += 1
            per_day[day]["rr_loss"] += abs(rr)
            per_day[day]["gross_loss"] += abs(delta)

    # KPIs globaux
    pf = None
    if gross_loss > 1e-12:
        pf = gross_profit / gross_loss
    expectancy = None
    if n_closes_used > 0:
        win_rate = wins / n_closes_used
        avg_win_rr = (rr_win_sum / wins) if wins else 0.0
        avg_loss_rr = (rr_loss_sum / losses) if losses else 0.0
        expectancy = win_rate * avg_win_rr - (1 - win_rate) * avg_loss_rr
    maxdd = None
    if equity_points:
        peak = equity_points[0][1]
        dd = 0.0
        for _, eq in equity_points:
            if eq > peak:
                peak = eq
            dd = min(dd, eq - peak)
        maxdd = abs(dd)  # en unités d'équité (ex: 0.07 = -7%)

    # Affichage
    print("=== Résumé global ===")
    print(f"- Opens:  {len(opens)}")
    print(f"- Closes exploitées: {n_closes_used} (sur {len(closes)} closes)")
    if pf is not None:
        print(f"- Profit Factor: {pf:.2f}")
    else:
        print("- Profit Factor: N/A (pas assez de closes)")
    if expectancy is not None:
        print(f"- Expectancy (R par trade): {expectancy:.3f}")
    else:
        print("- Expectancy: N/A (pas assez de closes)")
    if maxdd is not None:
        print(f"- Max Drawdown (équity): {maxdd*100:.2f}%")
    else:
        print("- Max Drawdown: N/A (pas assez de closes)")

    print("\n=== Par jour (UTC) ===")
    for day in sorted(per_day.keys()):
        d = per_day[day]
        line = [f"{day} | open={d['n_open']} close={d['n_close']}"]
        if d["wins"]+d["losses"] > 0:
            avg_win = d["rr_win"]/d["wins"] if d["wins"] else 0.0
            avg_los = d["rr_loss"]/d["losses"] if d["losses"] else 0.0
            pf_day = (d["gross_profit"]/d["gross_loss"]) if d["gross_loss"]>1e-12 else None
            exp_day = ( (d["wins"]/(d["wins"]+d["losses"]))*avg_win
                        - ( (d["losses"]/(d["wins"]+d["losses"])) * avg_los ) )
            line.append(f"wins={d['wins']} losses={d['losses']} PF={pf_day:.2f}" if pf_day is not None else f"wins={d['wins']} losses={d['losses']} PF=N/A")
            line.append(f"Exp={exp_day:.3f}")
        print("  " + " | ".join(line))

    # Conseils suivant données
    print("\n=== Notes ===")
    if n_closes_used == 0:
        print("- Aucun trade clôturé exploitable: PF/Expectancy/DD indisponibles. Laisse tourner 1–2 jours.")
    else:
        if pf is not None and pf < 1.30:
            print("- PF < 1.30: revoir filtres/gating, R:R, ou réduire le risque.")
        if maxdd is not None and maxdd > 0.12:
            print("- MaxDD > 12%: durcir le gating ou baisser le risque.")
        if expectancy is not None and expectancy <= 0:
            print("- Expectancy ≤ 0: stratégie non positive; vérifier le mix symboles et set-ups.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
