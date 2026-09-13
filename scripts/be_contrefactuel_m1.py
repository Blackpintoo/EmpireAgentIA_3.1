# -*- coding: utf-8 -*-
"""
Contrefactuel break-even sur barres M1 broker (donnees exactes).
A lancer sur la machine de prod, terminal MT5 ouvert, dans le venv du bot :
    python scripts/be_contrefactuel_m1.py
Lecture seule (copy_rates_range uniquement), aucun ordre envoye.
Sortie : tableau par seuil + data/compte_<login>/be_contrefactuel_m1.csv

Convention temporelle (FIX 2026-08-15) :
  - Tout timestamp manipule par ce script est TZ-AWARE UTC (suffixe _utc).
  - L'heure serveur broker (UTC+3) n'existe qu'a la frontiere MT5, dans
    _borne_requete_mt5() et _epoch_serveur_vers_utc() : jamais ailleurs.
"""
import csv, sys
from datetime import timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd
import numpy as np

RACINE = Path(__file__).resolve().parents[1]
SEUILS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
LOCK_R = 0.05  # niveau de sortie BE simule : entry + 0.05R (offset/spread)
DECALAGE_SERVEUR = timedelta(hours=3)  # heure serveur broker = UTC+3 (verifie le 02/08)


def _borne_requete_mt5(dt_utc):
    """UTC tz-aware -> datetime pour copy_rates_range.

    L'API python MT5 interprete le datetime fourni comme des secondes epoch
    'UTC', mais le serveur indexe ses barres sur SON horloge (UTC+3). On
    fournit donc la valeur murale serveur, etiquetee UTC uniquement pour
    satisfaire l'API. Ce datetime ne doit JAMAIS etre compare aux _utc.
    """
    return (dt_utc + DECALAGE_SERVEUR).replace(tzinfo=timezone.utc)


def _epoch_serveur_vers_utc(col_time):
    """Champ 'time' des barres (epoch estampille heure serveur) -> Series tz-aware UTC."""
    return pd.to_datetime(col_time, unit="s", utc=True) - DECALAGE_SERVEUR


def barres_m1(symbole, t0_utc, t1_utc):
    """t0_utc/t1_utc : tz-aware UTC. Retourne les barres M1 dans [t0_utc, t1_utc]."""
    r = mt5.copy_rates_range(
        symbole, mt5.TIMEFRAME_M1,
        _borne_requete_mt5(t0_utc - timedelta(minutes=10)),
        _borne_requete_mt5(t1_utc + timedelta(minutes=10)),
    )
    if r is None or len(r) == 0:
        return None
    df = pd.DataFrame(r)
    df["ts_utc"] = _epoch_serveur_vers_utc(df["time"])
    return df[(df.ts_utc >= t0_utc) & (df.ts_utc <= t1_utc)]  # tz-aware des deux cotes


def sequencage(df, sens, entry, rdist, seuil):
    """Retourne (touche, coupe, ambigu). coupe = retrace <= LOCK_R APRES la barre de touche."""
    if sens > 0:
        fav = (df.high.values - entry) / rdist
        adv = (df.low.values - entry) / rdist
    else:
        fav = (entry - df.low.values) / rdist
        adv = (entry - df.high.values) / rdist
    touche = fav >= seuil
    if not touche.any():
        return False, False, False
    i = int(np.argmax(touche))
    coupe = bool((adv[i + 1:] <= LOCK_R).any())
    ambigu = bool(adv[i] <= LOCK_R) and not coupe  # meme barre : ordre intra-barre inconnu
    return True, coupe, ambigu


def main():
    if not mt5.initialize():
        sys.exit(f"MT5 initialize KO: {mt5.last_error()}")
    login = mt5.account_info().login
    dossier = RACINE / "data" / f"compte_{login}"
    out = pd.read_csv(dossier / "trade_outcomes.csv")
    mfe = pd.read_csv(dossier / "trade_mfe.csv").drop_duplicates("ticket", keep="last")
    tl = pd.read_csv(RACINE / "data" / "trades_log.csv")
    tl = tl[tl.ok == True][["ticket", "ts_utc"]].rename(columns={"ts_utc": "ts_open"})
    d = out.merge(mfe[["ticket", "sl_orig"]], on="ticket").merge(tl, on="ticket", how="left")
    d = d.dropna(subset=["ts_open", "sl_orig"])
    # tz-aware UTC de bout en bout — aucun .replace(tzinfo=None) dans ce script
    d["ts_open_utc"] = pd.to_datetime(d.ts_open, format="ISO8601", utc=True)
    d["ts_close_utc"] = pd.to_datetime(d.timestamp, format="ISO8601", utc=True)
    d["rdist"] = (d.entry_price - d.sl_orig).abs()
    d["sens"] = np.where(d.direction == "LONG", 1, -1)

    lignes = []
    bilan = {x: dict(sauves=0.0, n_s=0, coupes=0.0, n_c=0, ambigus=0.0, n_a=0) for x in SEUILS}
    for _, t in d.iterrows():
        df = barres_m1(t.symbol, t.ts_open_utc, t.ts_close_utc)
        if df is None or len(df) < 2 or t.rdist <= 0:
            lignes.append([t.ticket, t.symbol, round(t.profit, 2), "barres_indisponibles"] + [""] * len(SEUILS))
            continue
        verdicts = []
        for x in SEUILS:
            touche, coupe, ambigu = sequencage(df, t.sens, t.entry_price, t.rdist, x)
            if not touche:
                verdicts.append("non_touche")
            elif t.profit < 0:
                bilan[x]["sauves"] += -t.profit; bilan[x]["n_s"] += 1
                verdicts.append("SAUVE")
            elif coupe and t.exit_type != "be":
                bilan[x]["coupes"] += t.profit; bilan[x]["n_c"] += 1
                verdicts.append("COUPE")
            elif ambigu and t.exit_type != "be":
                bilan[x]["ambigus"] += t.profit; bilan[x]["n_a"] += 1
                verdicts.append("ambigu")
            else:
                verdicts.append("sain")
        lignes.append([t.ticket, t.symbol, round(t.profit, 2), "ok"] + verdicts)

    chemin = dossier / "be_contrefactuel_m1.csv"
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticket", "symbole", "pnl", "statut"] + [f"seuil_{x}" for x in SEUILS])
        w.writerows(lignes)

    print(f"\n{len(d)} trades evalues sur barres M1 — detail: {chemin}\n")
    print("seuil | sauves (n, USD) | coupes (n, USD) | ambigus (n, USD) | NET (hors ambigus) | NET pire cas")
    for x in SEUILS:
        b = bilan[x]
        net = b["sauves"] - b["coupes"]
        print(f" {x:.1f}R | {b['n_s']:2d}  {b['sauves']:8.2f} | {b['n_c']:2d}  {b['coupes']:8.2f} |"
              f" {b['n_a']:2d}  {b['ambigus']:8.2f} | {net:+9.2f} | {net - b['ambigus']:+9.2f}")
    mt5.shutdown()


if __name__ == "__main__":
    main()
