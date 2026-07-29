# -*- coding: utf-8 -*-
"""
tools/test_news_sources.py — Valide les flux d'actualite et montre ce que
l'agent news voit reellement.

A lancer sur la machine qui a acces a Internet :
    .venv\\Scripts\\python.exe tools\\test_news_sources.py
    .venv\\Scripts\\python.exe tools\\test_news_sources.py --symbol XAUUSD --details

Ne modifie rien. Sert a :
  - reperer les flux morts ou trop lents, pour les retirer du registre ;
  - verifier qu'un instrument recoit bien des sources pertinentes ;
  - inspecter la ponderation appliquee a chaque article.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

try:
    from utils import news_sources as NS
except Exception as e:
    print("[ERREUR] impossible d'importer utils/news_sources.py :", e)
    sys.exit(1)


def sante(symbols):
    vus, rows = set(), []
    for sym in symbols:
        for r in NS.health_report(sym):
            if r["id"] in vus:
                continue
            vus.add(r["id"])
            rows.append(r)
    rows.sort(key=lambda r: (r["tier"], not r["ok"], r["id"]))

    print("=" * 78)
    print("  ETAT DES FLUX")
    print("=" * 78)
    print("  %-16s %5s %8s %9s %7s   %s" % ("flux", "tier", "etat", "articles", "ms", "libelle"))
    for r in rows:
        etat = "OK" if r["ok"] else "MORT"
        print("  %-16s %5d %8s %9d %7d   %s" % (
            r["id"], r["tier"], etat, r["n"], r["ms"], r["label"][:34]))

    ok = [r for r in rows if r["ok"]]
    print("\n  %d/%d flux vivants" % (len(ok), len(rows)))
    for t in (1, 2, 3, 4):
        tt = [r for r in rows if r["tier"] == t]
        oo = [r for r in tt if r["ok"]]
        if tt:
            etiq = NS.TIER_LABELS.get(t, "?")
            marque = "  <-- AUCUN, la couverture de ce niveau est perdue" if not oo else ""
            print("    tier %d (%-16s) : %d/%d%s" % (t, etiq, len(oo), len(tt), marque))

    morts = [r["id"] for r in rows if not r["ok"]]
    if morts:
        print("\n  Flux a signaler pour retrait du registre :")
        print("   ", ", ".join(morts))
    lents = [r for r in rows if r["ok"] and r["ms"] > 3000]
    if lents:
        print("\n  Flux lents (>3 s), candidats au retrait :")
        for r in lents:
            print("    %-16s %d ms" % (r["id"], r["ms"]))
    return rows


def apercu(symbol, details=False, n=12):
    print("\n" + "=" * 78)
    print("  CE QUE L'AGENT VOIT POUR %s  (classe : %s)" % (symbol, NS.classify_symbol(symbol)))
    print("=" * 78)
    srcs = NS.feeds_for_symbol(symbol)
    print("  %d source(s) selectionnee(s) :" % len(srcs))
    for s in srcs:
        print("    tier %d  %-16s %s" % (s["tier"], s["id"], s.get("label", "")))

    t0 = time.time()
    items = NS.collect(symbol)
    dt = time.time() - t0
    print("\n  %d article(s) retenu(s) en %.1f s" % (len(items), dt))
    if not items:
        print("  Aucun article. Verifie l'acces reseau et l'etat des flux ci-dessus.")
        return

    par_tier = {}
    for it in items:
        par_tier.setdefault(it["tier"], 0)
        par_tier[it["tier"]] += 1
    print("  repartition par tier : " + ", ".join(
        "tier %d = %d" % (t, par_tier[t]) for t in sorted(par_tier)))
    echos = sum(1 for it in items if int(it.get("echo_count", 1)) > 1)
    print("  sujets repris par plusieurs redactions : %d" % echos)

    print("\n  Les %d articles les plus lourds :" % min(n, len(items)))
    print("  %7s %5s %6s %6s %5s  %s" % ("poids", "tier", "pert.", "frais.", "repr", "titre"))
    for it in items[:n]:
        print("  %7.2f %5d %6.2f %6.2f %5d  %s" % (
            it.get("weight", 0), it["tier"], it.get("relevance", 0),
            it.get("freshness", 0), it.get("echo_count", 1),
            (it.get("title", "") or "")[:52]))

    if details:
        print("\n  Detail complet :")
        for it in items:
            print("   [%s] %s" % (it.get("source_label", ""), it.get("title", "")))
            print("      poids=%.2f  lien=%s" % (it.get("weight", 0), it.get("link", "")[:70]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="n'analyser qu'un symbole")
    ap.add_argument("--details", action="store_true", help="lister tous les articles")
    ap.add_argument("--skip-health", action="store_true", help="passer l'etat des flux")
    a = ap.parse_args()

    symbols = [a.symbol] if a.symbol else ["NAS100", "SP500", "XAUUSD", "AUDUSD", "USDJPY", "BTCUSD"]

    if not a.skip_health:
        sante(symbols)

    for sym in symbols:
        apercu(sym, details=a.details)

    print("\n" + "=" * 78)
    print("  Termine. Signale a Claude les flux MORTS pour qu'il les retire.")
    print("=" * 78)


if __name__ == "__main__":
    main()
