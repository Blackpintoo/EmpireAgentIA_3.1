# -*- coding: utf-8 -*-
"""
tools/entonnoir.py — qui refuse les propositions, et dans quelles proportions.

AJOUT 2026-08-02.

Sur la periode du 31/07 au 02/08, 1 325 propositions sur les 6 symboles reels
n'ont donne que 9 executions — 0,68 %. Impossible de dire si les 99,3 %
restants relevent d'un filtrage sain ou d'un blocage involontaire : seuls
`news-freeze` et `live-guard` ecrivaient dans logs/guards.log.

Depuis le meme jour, `Orchestrator._appliquer_refus` y ecrit une ligne
`garde:<nom>` pour CHAQUE refus des 20 gardes extraits en P2. Cet outil les
agrege.

    python tools/entonnoir.py
    python tools/entonnoir.py --symbole XAUUSD --depuis 2026-08-02
"""
import argparse
import collections
import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

GUARDS = Path("logs") / "guards.log"


def lire(depuis=None, symbole=None):
    lignes = []
    if not GUARDS.exists():
        return lignes
    with GUARDS.open(encoding="utf-8", errors="replace") as fh:
        for l in fh:
            p = l.rstrip("\n").split("|", 3)
            if len(p) < 3:
                continue
            try:
                t = dt.datetime.fromisoformat(p[0])
            except Exception:
                continue
            if depuis and t < depuis:
                continue
            if symbole and p[1].upper() != symbole.upper():
                continue
            lignes.append((t, p[1], p[2], p[3] if len(p) > 3 else ""))
    return lignes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbole", default=None)
    ap.add_argument("--depuis", default=None,
                    help="date ISO, ex. 2026-08-02 (defaut : 7 derniers jours)")
    a = ap.parse_args()

    depuis = None
    if a.depuis:
        depuis = dt.datetime.fromisoformat(a.depuis).replace(tzinfo=dt.timezone.utc)

    lignes = lire(depuis, a.symbole)
    if not lignes:
        print("Aucun evenement de garde sur la periode.")
        print("Si le fichier est vide, c'est que le bot n'a pas encore tourne")
        print("avec la journalisation des gardes (ajoutee le 02/08/2026).")
        return 0

    gardes = [l for l in lignes if l[2].startswith("garde:")]
    autres = [l for l in lignes if not l[2].startswith("garde:")]

    print("=" * 74)
    print("  ENTONNOIR DES REFUS  —  %d evenement(s)" % len(lignes))
    print("  du %s au %s" % (min(l[0] for l in lignes).strftime("%Y-%m-%d %H:%M"),
                             max(l[0] for l in lignes).strftime("%Y-%m-%d %H:%M")))
    print("=" * 74)

    if not gardes:
        print("\n  Aucune ligne 'garde:*'. Le bot tourne encore avec l'ancien")
        print("  code : seuls news-freeze et live-guard sont traces.")
    else:
        c = collections.Counter(l[2][len("garde:"):] for l in gardes)
        total = sum(c.values())
        print("\n  REFUS PAR GARDE (%d au total)\n" % total)
        print("  %-30s %8s %7s" % ("garde", "refus", "part"))
        for nom, n in c.most_common():
            print("  %-30s %8d %6.1f%%" % (nom, n, 100 * n / total))

        print("\n  REFUS PAR SYMBOLE\n")
        par_sym = collections.Counter(l[1] for l in gardes)
        for sym, n in par_sym.most_common():
            top = collections.Counter(
                l[2][len("garde:"):] for l in gardes if l[1] == sym).most_common(2)
            detail = ", ".join("%s %d" % (k, v) for k, v in top)
            print("  %-10s %6d   (%s)" % (sym, n, detail))

        print("\n  Un symbole dont un seul garde concentre la quasi-totalite des")
        print("  refus merite un examen : c'est la signature d'un blocage")
        print("  involontaire plutot que d'un filtrage.")

    if autres:
        print("\n  AUTRES GARDES (hors extraction P2)\n")
        for tag, n in collections.Counter(l[2] for l in autres).most_common():
            print("  %-30s %8d" % (tag, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
