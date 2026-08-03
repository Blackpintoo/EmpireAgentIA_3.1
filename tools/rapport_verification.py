# -*- coding: utf-8 -*-
"""
tools/rapport_verification.py — rassemble en UN fichier tout ce qu'il faut
pour verifier le comportement du bot en conditions reelles.

AJOUT 2026-08-03.

Pourquoi
--------
Le pont qui me permet de lire les fichiers de la machine sert des copies
PERIMEES des qu'un chemin a deja ete lu une fois : guards.log, pm_state.json
et trade_mfe.csv m'arrivaient dans leur version de la veille, alors que les
metadonnees (taille, date) etaient a jour. J'ai failli conclure sur des
donnees mortes.

Seuls les chemins JAMAIS lus arrivent intacts. Ce script ecrit donc son
rapport sous un nom horodate, unique par execution.

    .venv\\Scripts\\python.exe tools\\rapport_verification.py

Il ne modifie rien. Il lit, compte, et ecrit un seul fichier texte dans
_transfert\\.
"""
import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
os.chdir(RACINE)
sys.path.insert(0, str(RACINE))

SORTIE = Path("_transfert")


def _lignes(f, n=None):
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            return fh.readlines() if n is None else fh.readlines()[-n:]
    except Exception:
        return []


def main() -> int:
    SORTIE.mkdir(parents=True, exist_ok=True)
    horodatage = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cible = SORTIE / ("verification_%s.txt" % horodatage)
    out = []
    e = out.append

    e("=" * 78)
    e("  RAPPORT DE VERIFICATION  —  %s UTC" % horodatage)
    e("=" * 78)

    # ---- 0. le code qui tourne -------------------------------------------
    e("")
    e("## 0. PROCESSUS ET VERSION")
    try:
        import subprocess
        head = subprocess.run(["git", "log", "--oneline", "-3"],
                              stdout=subprocess.PIPE).stdout.decode("utf-8", "replace")
        e(head.rstrip())
    except Exception as ex:
        e("git indisponible : %s" % ex)
    for f in ("data/bot.pid", "data/selftest_state.json"):
        e("")
        e("--- %s ---" % f)
        try:
            e(Path(f).read_text(encoding="utf-8").strip())
        except Exception as ex:
            e("(absent : %s)" % ex)

    # ---- 1. positions -----------------------------------------------------
    e("")
    e("## 1. POSITIONS  (pm_state vs open_positions)")
    for f in ("data/pm_state.json", "data/open_positions.json"):
        e("")
        e("--- %s ---" % f)
        try:
            e(Path(f).read_text(encoding="utf-8").strip())
        except Exception as ex:
            e("(illisible : %s)" % ex)

    log = "logs/empire_agent.log"
    e("")
    e("--- hoquets [PM_DIAG] a 0 position ---")
    zero = collections.Counter()
    une = collections.Counter()
    absents = []
    for l in _lignes(log):
        m = re.search(r"\[PM_DIAG\] (\w+): (\d+) position", l)
        if m:
            (zero if m.group(2) == "0" else une)[m.group(1)] += 1
        if "absent de la lecture MT5" in l:
            absents.append(l.strip()[:160])
    for sym in sorted(set(zero) | set(une)):
        e("  %-8s lectures a 0 : %-6d | lectures a >=1 : %d" % (sym, zero[sym], une[sym]))
    e("")
    e("  lignes 'absent de la lecture MT5' (protection en action) : %d" % len(absents))
    for l in absents[-10:]:
        e("    " + l)
    e("")
    e("  'Cleaned ghost positions' depuis le demarrage :")
    for l in [x for x in _lignes(log) if "Cleaned ghost" in x][-10:]:
        e("    " + l.strip()[:160])

    # ---- 3. RISK_TRACE ----------------------------------------------------
    e("")
    e("## 3. RISK_TRACE")
    traces = [l.strip() for l in _lignes(log) if "[RISK_TRACE]" in l]
    e("  %d trace(s)" % len(traces))
    for l in traces[-25:]:
        e("    " + l[:200])

    # ---- 4. entonnoir -----------------------------------------------------
    e("")
    e("## 4. ENTONNOIR DES REFUS")
    g = Path("logs/guards.log")
    if not g.exists():
        e("  logs/guards.log absent")
    else:
        par_garde = collections.Counter()
        par_sym = collections.Counter()
        detail = collections.defaultdict(collections.Counter)
        autres = collections.Counter()
        premiere = derniere = None
        with g.open(encoding="utf-8", errors="replace") as fh:
            for l in fh:
                p = l.rstrip("\n").split("|", 3)
                if len(p) < 3:
                    continue
                try:
                    t = dt.datetime.fromisoformat(p[0])
                except Exception:
                    continue
                if p[2].startswith("garde:"):
                    nom = p[2][6:]
                    premiere = premiere or t
                    derniere = t
                    par_garde[nom] += 1
                    par_sym[p[1]] += 1
                    detail[p[1]][nom] += 1
                else:
                    autres[p[2]] += 1
        e("  lignes 'garde:' : %d" % sum(par_garde.values()))
        if premiere:
            e("  de %s a %s" % (premiere, derniere))
        e("")
        e("  REFUS PAR GARDE")
        tot = sum(par_garde.values()) or 1
        for nom, n in par_garde.most_common():
            e("    %-30s %7d  %5.1f%%" % (nom, n, 100 * n / tot))
        e("")
        e("  REFUS PAR SYMBOLE (et gardes dominants)")
        for sym, n in par_sym.most_common():
            top = ", ".join("%s=%d" % (k, v) for k, v in detail[sym].most_common(4))
            e("    %-9s %7d   %s" % (sym, n, top))
        e("")
        e("  AUTRES GARDES (hors extraction P2)")
        for tag, n in autres.most_common(12):
            e("    %-30s %7d" % (tag, n))

    # ---- 5. trade_mfe -----------------------------------------------------
    e("")
    e("## 5. TRADE_MFE")
    try:
        from utils.account_scope import chemin_donnees
        mfe = Path(chemin_donnees("trade_mfe.csv"))
    except Exception:
        mfe = Path("data/trade_mfe.csv")
    e("  fichier : %s" % mfe)
    lignes = _lignes(mfe)
    if not lignes:
        e("  (vide ou absent)")
    else:
        e("  entete : %s" % lignes[0].strip())
        e("  %d ligne(s) de donnees" % (len(lignes) - 1))
        e("")
        e("  20 dernieres lignes :")
        for l in lignes[-20:]:
            e("    " + l.rstrip()[:190])

    # ---- 6. backoff et Finnhub -------------------------------------------
    e("")
    e("## 6. BACKOFF DE CLOTURE ET FINNHUB")
    tous = _lignes(log)
    e("  lignes [PM_TIMEOUT]              : %d" % sum(1 for l in tous if "[PM_TIMEOUT]" in l))
    e("  lignes 'cloture refusee'         : %d" % sum(1 for l in tous if "cloture refusee" in l))
    e("  lignes 'Failed to close position' : %d" % sum(1 for l in tous if "Failed to close position" in l))
    e("  lignes Finnhub 403               : %d" % sum(1 for l in tous if "Finnhub" in l and "403" in l))
    e("  dont en ERROR                    : %d" % sum(1 for l in tous
                                                     if "Finnhub" in l and "403" in l and "ERROR" in l))
    e("")
    e("  echantillon Finnhub :")
    for l in [x for x in tous if "Finnhub" in x][-5:]:
        e("    " + l.strip()[:190])
    e("")
    e("  periode couverte par %s :" % log)
    if tous:
        e("    debut : %s" % tous[0][:19])
        e("    fin   : %s" % tous[-1][:19])
        e("    %d lignes" % len(tous))

    cible.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("Rapport ecrit : %s" % cible)
    print("Envoie ce fichier a Claude (ou dis-lui simplement qu'il est pret).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
