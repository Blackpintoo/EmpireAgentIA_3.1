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

    # ---- 7. RISK_TRACE par symbole ---------------------------------------
    # AJOUT 2026-08-17. La distorsion de risque etait etablie sur BTCUSD
    # (1R ~487 USD au lieu de ~255). Question ouverte : le plafonnement
    # max_volume produit-il le meme ecart ailleurs ?
    e("")
    e("## 7. RISK_TRACE PAR SYMBOLE  (distorsion de dimensionnement)")
    rt = re.compile(
        r"\[RISK_TRACE\] (\w+) (\w+): lots=(\S+) dist=([\d.]+) pts "
        r"pip_value=([\d.]+) -> risque_engage=([\d.]+) USD \| budget=(\S+ USD|inconnu)"
        r".*?ratio=([\d.]+)x")
    par_sym_rt = collections.defaultdict(list)
    erreurs_rt = collections.Counter()
    for l in tous:
        m = rt.search(l)
        if m:
            par_sym_rt[m.group(1)].append({
                "sens": m.group(2), "lots": m.group(3),
                "risque": float(m.group(6)), "ratio": float(m.group(8)),
                "ts": l[:19],
            })
        elif "[RISK_TRACE]" in l and "vaut" in l:
            ms = re.search(r"\[RISK_TRACE\] (\w+): le risque engage vaut ([\d.]+)x", l)
            if ms:
                erreurs_rt[ms.group(1)] += 1

    if not par_sym_rt:
        e("  Aucune ligne [RISK_TRACE] exploitable.")
        e("  ATTENTION : [RISK_TRACE] n'est emis qu'APRES les gardes de session")
        e("  et juste avant order_send. Un symbole bloque par session_filter")
        e("  n'en produit AUCUNE — l'absence ne prouve donc rien sur ce symbole.")
    else:
        e("  %-9s %5s %10s %10s %10s %8s" % ("SYMBOLE", "n", "ratio_min",
                                             "ratio_med", "ratio_max", "hors_[.75-1.25]"))
        for sym in sorted(par_sym_rt, key=lambda s: -len(par_sym_rt[s])):
            r = sorted(x["ratio"] for x in par_sym_rt[sym])
            hors = sum(1 for x in r if x > 1.25 or x < 0.75)
            e("  %-9s %5d %10.2f %10.2f %10.2f %8d" %
              (sym, len(r), r[0], r[len(r) // 2], r[-1], hors))
        e("")
        e("  Lignes ERROR '[RISK_TRACE] ... vaut Nx le budget' par symbole :")
        for sym, n in erreurs_rt.most_common():
            e("    %-9s %d" % (sym, n))
        e("")
        e("  5 dernieres traces par symbole :")
        for sym in sorted(par_sym_rt):
            e("    --- %s ---" % sym)
            for x in par_sym_rt[sym][-5:]:
                e("      %s %-5s lots=%-6s risque=%8.2f USD ratio=%.2fx"
                  % (x["ts"], x["sens"], x["lots"], x["risque"], x["ratio"]))

    e("")
    e("  Plafonnements max_volume observes (contexte du point 2) :")
    cap = collections.Counter()
    for l in tous:
        m = re.search(r"\[RISK\] (\w+): Volume ([\d.]+) depasse limite "
                      r"max_volume=([\d.]+)", l.replace("é", "e"))
        if m:
            cap[m.group(1)] += 1
    for sym, n in cap.most_common():
        avec_trace = len(par_sym_rt.get(sym, []))
        e("    %-9s plafonne %3d fois | traces RISK_TRACE ensuite : %d" % (sym, n, avec_trace))
    if not cap:
        e("    aucun")

    # ---- 8. tracabilite des agents en conditions reelles ------------------
    # AJOUT 2026-08-17. Le champ agents_detail a ete valide en bac a sable ;
    # ici on lit la FIN du vrai journal, sans le charger en entier.
    e("")
    e("## 8. TRACABILITE DES AGENTS  (agents_snap.jsonl)")
    snap = Path("data/agents_snap.jsonl")
    if not snap.exists():
        e("  data/agents_snap.jsonl absent")
    else:
        taille = snap.stat().st_size
        e("  taille : %.1f Mo" % (taille / 1024 / 1024))
        _rot = sorted(p.name for p in Path("data").glob("agents_snap.jsonl.*"))
        e("  rotation : %s" % (", ".join(_rot) if _rot else "aucun fichier .1/.2/.3"))
        lignes_fin = []
        try:
            with snap.open("rb") as fh:
                fh.seek(max(0, taille - 400_000))
                lignes_fin = fh.read().decode("utf-8", "replace").splitlines()[1:]
        except Exception as ex:
            e("  lecture impossible : %s" % ex)
        recs = []
        for l in lignes_fin[-400:]:
            try:
                recs.append(json.loads(l))
            except Exception:
                continue
        e("  %d enregistrement(s) lus en fin de fichier" % len(recs))
        avec = [r for r in recs if r.get("agents_detail")]
        e("  dont avec agents_detail : %d" % len(avec))
        if recs:
            e("  horodatage du plus recent : %s" % recs[-1].get("ts_utc"))
        if not avec:
            e("")
            e("  Aucun agents_detail. Deux causes possibles, a departager par la")
            e("  section 0 : soit le processus tourne encore l'ancien code (le")
            e("  commit 5e9c6d7 n'est pas dans le HEAD affiche plus haut), soit il")
            e("  a ete deploye mais le bot n'a pas ete redemarre depuis.")
        else:
            par_sym_tr = collections.Counter(r.get("symbol") for r in avec)
            e("")
            e("  Par symbole :")
            for sym, n in par_sym_tr.most_common():
                e("    %-9s %d" % (sym, n))
            cles = collections.Counter()
            motifs = collections.Counter()
            for r in avec:
                for agent, d in (r["agents_detail"] or {}).items():
                    cles[agent] += 1
                    if isinstance(d, dict) and d.get("reason"):
                        motifs["%s:%s" % (agent, d["reason"])] += 1
            e("")
            e("  Par agent :")
            for a, n in cles.most_common():
                e("    %-12s %d" % (a, n))
            e("")
            e("  Motifs rencontres :")
            for m, n in motifs.most_common(10):
                e("    %-34s %d" % (m, n))
            e("")
            e("  3 derniers agents_detail (bruts) :")
            for r in avec[-3:]:
                e("    %s %-9s %s" % (r.get("ts_utc", "?")[:19], r.get("symbol"),
                                      json.dumps(r["agents_detail"], ensure_ascii=False)[:400]))

    # ---- 9. repetition des collectes news --------------------------------
    e("")
    e("## 9. REPETITION DES LIGNES [NEWS_SRC]")
    ns = collections.defaultdict(list)
    for l in tous:
        m = re.search(r"\[NEWS_SRC\] (\w+): (\d+) sources, (\d+) bruts", l)
        if m:
            ns[m.group(1)].append((l[:19], m.group(2), m.group(3)))
    for sym, v in sorted(ns.items(), key=lambda kv: -len(kv[1]))[:6]:
        e("  %-9s %d ligne(s)" % (sym, len(v)))
        for x in v[-4:]:
            e("      %s  sources=%s bruts=%s" % x)
    if ns:
        e("")
        e("  Lecture : des comptes 'bruts' IDENTIQUES d'une ligne a l'autre en")
        e("  moins de 600 s indiquent un service par le cache de flux, pas un")
        e("  nouvel appel reseau. Des comptes qui varient indiqueraient l'inverse.")

    cible.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("Rapport ecrit : %s" % cible)
    print("Envoie ce fichier a Claude (ou dis-lui simplement qu'il est pret).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
