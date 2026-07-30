# -*- coding: utf-8 -*-
"""
tools/adopter_historique_compte.py — rattache un historique hérité au compte
MT5 courant, de façon explicite.

AJOUT 2026-07-30 (P5).

Depuis P5, les données de performance sont cloisonnées par compte :

    data/performance/compte_<numero>/tracker_<SYMBOLE>.json
    data/compte_<numero>/trade_outcomes.csv
    data/compte_<numero>/deals_history.csv

Les fichiers historiques, écrits avant ce cloisonnement, ne portent aucune
trace du compte qui les a produits. Le bot les IGNORE volontairement : les
adopter automatiquement reviendrait à laisser un compte fermé piloter les
seuils adaptatifs et le live guard du compte courant.

Cet outil fait l'adoption si — et seulement si — tu confirmes que cet
historique appartient bien au compte courant.

    python tools/adopter_historique_compte.py            # montre ce qui serait fait
    python tools/adopter_historique_compte.py --appliquer

Rien n'est supprimé : les fichiers hérités restent en place. L'adoption est
une copie.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from utils.account_scope import numero_compte, repertoire_compte  # noqa: E402

PERF = Path("data") / "performance"


def _paires():
    """Renvoie [(source_heritee, destination_compte)] pour tout ce qui existe."""
    paires = []
    dossier_perf = PERF / ("compte_%s" % numero_compte())
    for src in sorted(PERF.glob("tracker_*.json")):
        paires.append((src, dossier_perf / src.name))
    glob_perf = PERF / "performance_tracker.json"
    if glob_perf.exists():
        paires.append((glob_perf, dossier_perf / glob_perf.name))
    for nom in ("trade_outcomes.csv", "deals_history.csv"):
        src = Path("data") / nom
        if src.exists():
            paires.append((src, repertoire_compte() / nom))
    return [(s, d) for s, d in paires if s.exists()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--appliquer", action="store_true",
                    help="effectue reellement la copie")
    ap.add_argument("--ecraser", action="store_true",
                    help="ecrase une destination deja presente")
    a = ap.parse_args()

    compte = numero_compte()
    paires = _paires()

    print("=" * 74)
    print("  ADOPTION DE L'HISTORIQUE — compte courant : %s" % compte)
    print("=" * 74)
    if compte == "inconnu":
        print("  Le numero de compte n'a pas pu etre lu (MT5_ACCOUNT absent du .env ?).")
        print("  Adopter un historique sous 'compte_inconnu' n'a aucun interet :")
        print("  corrige d'abord le .env, puis relance.")
        return 2
    if not paires:
        print("  Aucun fichier herite a adopter. Rien a faire.")
        return 0

    for src, dst in paires:
        etat = "DEJA PRESENT" if dst.exists() else "a copier"
        print("  %-52s -> %s   [%s]" % (str(src), str(dst.parent), etat))

    if not a.appliquer:
        print()
        print("  Simulation uniquement. Ajoute --appliquer pour effectuer la copie.")
        print("  N'adopte cet historique que s'il provient bien du compte %s." % compte)
        return 0

    copies, ignores = 0, 0
    for src, dst in paires:
        if dst.exists() and not a.ecraser:
            ignores += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copies += 1

    print()
    print("  %d fichier(s) copie(s), %d ignore(s) (destination existante)." % (copies, ignores))
    print("  Les fichiers d'origine sont intacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
