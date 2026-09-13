# -*- coding: utf-8 -*-
"""
tools/rapport_cycles.py — lire data/compte_<n>/cycles.csv.

AJOUT 2026-09-13.

Sert d'abord a VERIFIER que le journal est bien inconditionnel : si le nombre
de cycles par symbole s'approche de 720 par jour de cotation, et si la
repartition des votes contient des WAIT, des desaccords et des agents absents,
alors le fichier n'est plus conditionne sur l'accord des agents — ce qui etait
tout le probleme de agents_snap.jsonl.

    python tools/rapport_cycles.py
    python tools/rapport_cycles.py --depuis 2026-09-14 --jusqu-a 2026-09-21
    python tools/rapport_cycles.py --symbole NAS100 --echantillon 10
"""
import argparse
import collections
import csv
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
os.chdir(RACINE)
sys.path.insert(0, str(RACINE))

from utils.journal_cycles import AGENTS, COLONNES, NOM_FICHIER  # noqa: E402

LIBELLE = {"L": "LONG", "S": "SHORT", "W": "WAIT", "-": "absent"}


def _fichiers():
    try:
        from utils.account_scope import chemin_donnees
        base = Path(chemin_donnees(NOM_FICHIER))
    except Exception:
        base = Path("data") / NOM_FICHIER
    trouves = [base] if base.exists() else []
    trouves += sorted(base.parent.glob(base.name + ".*"))
    return trouves


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depuis", default=None, help="AAAA-MM-JJ inclus")
    ap.add_argument("--jusqu-a", dest="jusqu_a", default=None, help="AAAA-MM-JJ inclus")
    ap.add_argument("--symbole", default=None)
    ap.add_argument("--echantillon", type=int, default=0,
                    help="afficher N lignes brutes, dont au moins un WAIT")
    a = ap.parse_args()

    fichiers = _fichiers()
    if not fichiers:
        print("Aucun journal de cycles trouve. Le fichier n'est cree qu'au")
        print("premier cycle apres deploiement — il n'y a pas de rattrapage.")
        return 1

    cycles = collections.Counter()          # symbole -> nb de lignes
    par_jour = collections.Counter()
    votes = {a_: collections.Counter() for a_ in AGENTS}
    directions = collections.Counter()
    gardes = collections.Counter()
    desaccords = 0
    total = 0
    echantillon, un_wait = [], False

    for f in fichiers:
        try:
            with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    ts = (row.get("ts_utc") or "")[:10]
                    if not ts:
                        continue
                    if a.depuis and ts < a.depuis:
                        continue
                    if a.jusqu_a and ts > a.jusqu_a:
                        continue
                    sym = row.get("symbole") or "?"
                    if a.symbole and sym != a.symbole:
                        continue
                    total += 1
                    cycles[sym] += 1
                    par_jour[ts] += 1
                    directions[row.get("direction") or "?"] += 1
                    g = row.get("garde") or ""
                    if g:
                        gardes[g] += 1
                    v = row.get("votes") or ""
                    for i, a_ in enumerate(AGENTS):
                        votes[a_][v[i] if i < len(v) else "-"] += 1
                    exprimes = {c for c in v if c in ("L", "S")}
                    if len(exprimes) > 1:
                        desaccords += 1
                    if a.echantillon:
                        if len(echantillon) < a.echantillon:
                            echantillon.append(row)
                            un_wait = un_wait or row.get("direction") == "W"
                        elif not un_wait and row.get("direction") == "W":
                            echantillon[-1] = row
                            un_wait = True
        except Exception as e:
            print("  %s illisible : %s" % (f, e))

    print("=" * 74)
    print("  JOURNAL DE CYCLES")
    print("=" * 74)
    print("fichiers : %s" % ", ".join(p.name for p in fichiers))
    print("taille   : %.1f Mo" % (sum(p.stat().st_size for p in fichiers) / 1024 / 1024))
    print("lignes retenues : %d" % total)
    if not total:
        print("Aucune ligne dans la periode demandee.")
        return 0
    jours = sorted(par_jour)
    print("periode  : %s -> %s (%d jour(s))" % (jours[0], jours[-1], len(jours)))

    print()
    print("CYCLES PAR SYMBOLE  (une ligne par cycle ET par timeframe)")
    for sym, n in cycles.most_common():
        print("  %-9s %7d lignes   ~%6.0f cycles/jour"
              % (sym, n, n / max(1, len(jours)) / 3))

    print()
    print("REPARTITION DES VOTES PAR AGENT")
    print("  %-11s %8s %8s %8s %8s" % ("AGENT", "LONG", "SHORT", "WAIT", "absent"))
    for a_ in AGENTS:
        c = votes[a_]
        print("  %-11s %7.1f%% %7.1f%% %7.1f%% %7.1f%%" % (
            a_, 100.0 * c["L"] / total, 100.0 * c["S"] / total,
            100.0 * c["W"] / total, 100.0 * c["-"] / total))

    print()
    print("DIRECTION RETENUE : %s" % {LIBELLE.get(k, k): v for k, v in directions.most_common()})
    print("lignes avec desaccord entre agents : %d (%.1f %%)"
          % (desaccords, 100.0 * desaccords / total))

    print()
    print("GARDES BLOQUANTS")
    if gardes:
        for g, n in gardes.most_common(15):
            print("  %-32s %6d  %5.1f%%" % (g, n, 100.0 * n / total))
    else:
        print("  aucun")

    print()
    print("CONTROLE D'INCONDITIONNALITE")
    ok = []
    ok.append(("des cycles en WAIT", directions.get("W", 0) > 0))
    ok.append(("des desaccords entre agents", desaccords > 0))
    ok.append(("des agents absents", any(votes[a_]["-"] for a_ in AGENTS)))
    ok.append(("des cycles bloques par un garde", bool(gardes)))
    for libelle, valeur in ok:
        print("  [%s] %s" % ("x" if valeur else " ", libelle))
    if all(v for _, v in ok):
        print("  -> le journal n'est pas conditionne sur l'accord des agents.")
    else:
        print("  -> attention : il manque au moins un cas. Soit la periode est")
        print("     trop courte, soit l'ecriture reste conditionnelle quelque part.")

    if echantillon:
        print()
        print("ECHANTILLON")
        print("  " + " | ".join(COLONNES))
        for row in echantillon:
            print("  " + " | ".join(str(row.get(c, "")) for c in COLONNES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
