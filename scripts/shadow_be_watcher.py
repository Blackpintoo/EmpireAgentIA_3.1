# -*- coding: utf-8 -*-
"""
Phase B — shadow break-even (aucun effet sur le trading reel).
A chaque cloture de trade, evalue sur barres M1 la grille de seuils BE
{0.4..0.9R} et journalise le verdict dans data/compte_<login>/shadow_be.csv.
Ne modifie JAMAIS un SL : lecture seule via copy_rates_range.

Usage (venv du bot, terminal MT5 ouvert) :
    python scripts/shadow_be_watcher.py              # une passe puis sortie
    python scripts/shadow_be_watcher.py --boucle 15  # re-scan toutes les 15 min
    python scripts/shadow_be_watcher.py --bilan      # tableau Go/NoGo
    python scripts/shadow_be_watcher.py --depuis 2026-07-31T00:00:00+00:00

Reutilise barres_m1/sequencage de be_contrefactuel_m1.py (meme dossier).
Convention temporelle identique : tout en tz-aware UTC, l'heure serveur
(UTC+3) reste confinee aux fonctions frontiere du module importe.
"""
import argparse, csv, sys, time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from be_contrefactuel_m1 import (  # noqa: E402
    barres_m1, sequencage, SEUILS, LOCK_R, RACINE, mt5,
)

PHASE_B_DEBUT = "2026-08-15T18:00:00+00:00"   # debut officiel de l'observation
EXCLUS = {"BTCUSD"}                            # hors perimetre (chantier dimensionnement)
CRITERES_GO = dict(n_trades_min=50, ratio_coupes_max=0.10, delta_r_min=2.0)


def _charger(dossier):
    out = pd.read_csv(dossier / "trade_outcomes.csv")
    mfe = pd.read_csv(dossier / "trade_mfe.csv").drop_duplicates("ticket", keep="last")
    tl = pd.read_csv(RACINE / "data" / "trades_log.csv")
    tl = tl[tl.ok == True][["ticket", "ts_utc"]].rename(columns={"ts_utc": "ts_open"})
    d = out.merge(mfe[["ticket", "sl_orig"]], on="ticket").merge(tl, on="ticket", how="left")
    d = d.dropna(subset=["ts_open", "sl_orig"])
    d["ts_open_utc"] = pd.to_datetime(d.ts_open, format="ISO8601", utc=True)
    d["ts_close_utc"] = pd.to_datetime(d.timestamp, format="ISO8601", utc=True)
    d["rdist"] = (d.entry_price - d.sl_orig).abs()
    d["sens"] = (d.direction == "LONG").map({True: 1, False: -1})
    return d


def _deja_vus(chemin):
    if not chemin.exists():
        return set()
    with open(chemin, encoding="utf-8") as f:
        return {int(r["ticket"]) for r in csv.DictReader(f)}


def une_passe(depuis_utc, verbeux=True):
    if not mt5.initialize():
        print(f"MT5 initialize KO: {mt5.last_error()} — nouvelle tentative au prochain cycle")
        return 0
    login = mt5.account_info().login
    dossier = RACINE / "data" / f"compte_{login}"
    chemin = dossier / "shadow_be.csv"
    vus = _deja_vus(chemin)
    d = _charger(dossier)
    d = d[(d.ts_close_utc >= depuis_utc) & (~d.ticket.isin(vus))]

    en_tetes = (["ts_close_utc", "ticket", "symbole", "direction", "pnl", "r_reel", "exit_type", "statut"]
                + [f"verdict_{x}" for x in SEUILS] + [f"delta_r_{x}" for x in SEUILS])
    nouveau = not chemin.exists()
    n_ecrits = 0
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nouveau:
            w.writerow(en_tetes)
        for _, t in d.iterrows():
            if t.symbol in EXCLUS:
                continue
            base = [t.ts_close_utc.isoformat(), int(t.ticket), t.symbol, t.direction,
                    round(t.profit, 2), round(t.r_multiple, 4), t.exit_type]
            if t.rdist <= 0:
                w.writerow(base + ["rdist_nul"] + [""] * (2 * len(SEUILS))); n_ecrits += 1; continue
            df = barres_m1(t.symbol, t.ts_open_utc, t.ts_close_utc)
            if df is None or len(df) < 2:
                w.writerow(base + ["barres_indisponibles"] + [""] * (2 * len(SEUILS))); n_ecrits += 1; continue
            verdicts, deltas = [], []
            for x in SEUILS:
                touche, coupe, ambigu = sequencage(df, t.sens, t.entry_price, t.rdist, x)
                if not touche:
                    verdicts.append("non_touche"); deltas.append(0.0)
                elif coupe or ambigu:
                    # BE simule serait sorti a ~ +LOCK_R au lieu du resultat reel
                    verdicts.append("SAUVE" if t.profit < 0 else ("COUPE" if coupe else "ambigu"))
                    deltas.append(round(LOCK_R - t.r_multiple, 4))
                else:
                    verdicts.append("sain"); deltas.append(0.0)
            w.writerow(base + ["ok"] + verdicts + deltas); n_ecrits += 1
            if verbeux:
                print(f"  {int(t.ticket)} {t.symbol} r={t.r_multiple:+.2f} -> "
                      + " ".join(f"{x}:{v}" for x, v in zip(SEUILS, verdicts)))
    mt5.shutdown()
    if verbeux:
        print(f"{n_ecrits} nouveau(x) trade(s) evalue(s) -> {chemin}")
    return n_ecrits


def bilan():
    if not mt5.initialize():
        sys.exit(f"MT5 initialize KO: {mt5.last_error()}")
    login = mt5.account_info().login
    mt5.shutdown()
    chemin = RACINE / "data" / f"compte_{login}" / "shadow_be.csv"
    if not chemin.exists():
        sys.exit("Aucun shadow_be.csv — lancer d'abord une passe.")
    d = pd.read_csv(chemin)
    d = d[d.statut == "ok"]
    n = len(d)
    n_gagnants = int((d.pnl > 0).sum())
    print(f"\nShadow BE — {n} trades evalues (hors BTCUSD), dont {n_gagnants} gagnants.")
    print("seuil | SAUVE | COUPE | ambigu | delta_R cumule | coupes/gagnants | Go ?")
    for x in SEUILS:
        v, dr = d[f"verdict_{x}"], pd.to_numeric(d[f"delta_r_{x}"], errors="coerce").fillna(0)
        ns, nc, na = int((v == "SAUVE").sum()), int((v == "COUPE").sum()), int((v == "ambigu").sum())
        delta = float(dr.sum())
        ratio = nc / n_gagnants if n_gagnants else 0.0
        go = (n >= CRITERES_GO["n_trades_min"] and ratio <= CRITERES_GO["ratio_coupes_max"]
              and delta >= CRITERES_GO["delta_r_min"])
        print(f" {x:.1f}R |  {ns:3d}  |  {nc:3d}  |  {na:3d}   |   {delta:+8.2f}    |"
              f"      {ratio:5.1%}     | {'GO' if go else ('n<50' if n < CRITERES_GO['n_trades_min'] else 'non')}")
    print(f"\nCriteres Go : n>={CRITERES_GO['n_trades_min']}, coupes/gagnants<="
          f"{CRITERES_GO['ratio_coupes_max']:.0%}, delta_R cumule>=+{CRITERES_GO['delta_r_min']:.0f}R.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boucle", type=int, nargs="?", const=15, default=None,
                   help="re-scan toutes les N minutes (defaut 15)")
    p.add_argument("--bilan", action="store_true", help="affiche le tableau Go/NoGo")
    p.add_argument("--depuis", default=PHASE_B_DEBUT,
                   help="n'evaluer que les trades clos apres cet instant (ISO, UTC)")
    a = p.parse_args()
    if a.bilan:
        bilan(); return
    depuis = pd.Timestamp(a.depuis)
    if depuis.tzinfo is None:
        depuis = depuis.tz_localize("UTC")
    if a.boucle:
        print(f"Watcher shadow BE demarre (cycle {a.boucle} min, depuis {depuis}). Ctrl+C pour arreter.")
        while True:
            try:
                une_passe(depuis)
            except Exception as e:  # jamais de crash de boucle : on reessaie au cycle suivant
                print(f"passe en erreur ({e}) — retentative au prochain cycle")
            time.sleep(a.boucle * 60)
    else:
        une_passe(depuis)


if __name__ == "__main__":
    main()
