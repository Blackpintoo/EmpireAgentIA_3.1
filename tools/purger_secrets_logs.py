# -*- coding: utf-8 -*-
"""
tools/purger_secrets_logs.py — retire les secrets en clair des journaux.

AJOUT 2026-08-02.

Ce qui s'est passe
------------------
La cle Finnhub a circule EN CLAIR dans logs/empire_agent.log, via l'URL
complete d'un appel en echec :

    …/calendar/economic?from=…&to=…&token=<cle>

Le masquage du 2 aout couvre les NOUVELLES lignes, mais il ne peut rien pour
celles deja ecrites — ni pour les fichiers de rotation .1, .2, … Ce script
les nettoie.

    python tools/purger_secrets_logs.py            # simulation
    python tools/purger_secrets_logs.py --appliquer

A LANCER BOT ARRETE. Le journal est ouvert en ecriture par le processus ;
le reecrire pendant qu'il tourne perdrait des lignes ou corromprait le
fichier. Le script refuse de s'executer si le VERROU DU BOT (data/bot.pid, pose au
demarrage) designe un processus vivant. Il ne se fie plus a la simple
presence d'un python.exe : pytest, un notebook ou un IDE en declenchaient
un faux positif.

Ce script ne remplace pas la regeneration de la cle. Une cle qui a fuite est
compromise, meme apres nettoyage des journaux : elle a pu etre lue entre-temps.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

RACINE = Path(os.environ.get("EMPIRE_RACINE") or
              Path(__file__).resolve().parent.parent).resolve()
os.chdir(RACINE)
sys.path.insert(0, str(RACINE))

MASQUE = "****"

# Memes motifs que utils/logger.py, pour que purge et masquage restent alignes.
MOTIFS = [
    re.compile(r"([?&](?:token|api_?key|apikey|access_token)=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"\b\d{9,}:[A-Za-z0-9_\-]{20,}\b"),
]

VARIABLES = ("FINNHUB_API_KEY", "ALPHA_VANTAGE_API_KEY", "NEWSAPI_KEY",
             "CRYPTOPANIC_TOKEN", "TELEGRAM_BOT_TOKEN", "MT5_PASSWORD")


def _secrets_du_env():
    """Valeurs litterales a effacer, lues depuis l'environnement et le .env."""
    valeurs = set()
    for v in VARIABLES:
        s = os.environ.get(v)
        if s and len(s) >= 8:
            valeurs.add(s)
    env = RACINE / ".env"
    if env.exists():
        try:
            for ligne in env.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" not in ligne or ligne.lstrip().startswith("#"):
                    continue
                cle, _, val = ligne.partition("=")
                if cle.strip() in VARIABLES:
                    val = val.strip().strip('"').strip("'")
                    if len(val) >= 8:
                        valeurs.add(val)
        except Exception:
            pass
    return valeurs


def _nettoyer(texte: str, litteraux) -> tuple:
    n = 0
    for lit in litteraux:
        if lit in texte:
            n += texte.count(lit)
            texte = texte.replace(lit, MASQUE)
    for motif in MOTIFS:
        texte, k = motif.subn(
            lambda m: (m.group(1) + MASQUE) if m.groups() else MASQUE, texte)
        n += k
    return texte, n


def _bot_actif():
    """
    FIX 2026-08-02 : on interroge le VERROU DU BOT (data/bot.pid), pas la
    liste des processus.

    L'ancienne version refusait d'agir des qu'un `python.exe` apparaissait
    dans tasklist. Elle a bloque la purge appelee depuis un test — pytest est
    un python.exe, le garde se declenchait donc sur le processus qui
    l'interrogeait. En production, un notebook, un IDE ou un autre outil de ce
    depot auraient produit le meme faux positif.
    """
    try:
        from utils.verrou_bot import bot_actif
        return bot_actif()
    except Exception as e:
        # Sans le module, on ne bloque pas : le garde protege d'une
        # maladresse, il ne doit pas devenir un point de panne.
        return False, "verrou indisponible (%s), on continue" % e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--forcer", action="store_true",
                    help="purger meme si un python.exe tourne (deconseille)")
    ap.add_argument("--racine", default=None,
                    help="repertoire a nettoyer (defaut : le depot)")
    a = ap.parse_args()
    if a.racine:
        os.chdir(Path(a.racine).resolve())

    litteraux = _secrets_du_env()
    fichiers = sorted(Path("logs").glob("*.log*")) if Path("logs").exists() else []
    fichiers += sorted(Path("reports").glob("*.jsonl")) if Path("reports").exists() else []

    print("=" * 74)
    print("  PURGE DES SECRETS DANS LES JOURNAUX")
    print("=" * 74)
    print("  %d valeur(s) litterale(s) lue(s) depuis le .env et l'environnement." % len(litteraux))
    print("  (elles ne sont pas affichees ici, c'est le but)")
    print()

    if not fichiers:
        print("  Aucun journal trouve.")
        return 0

    if a.appliquer and not a.forcer:
        actif, pourquoi = _bot_actif()
        if actif:
            print("  [ARRET] %s" % pourquoi)
            print("  Arrete le bot avant de purger : reecrire un journal ouvert")
            print("  en ecriture perdrait des lignes. --forcer pour passer outre.")
            return 2
        print("  Verrou : %s" % pourquoi)
        print()

    total = 0
    for f in fichiers:
        try:
            brut = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print("  %-40s illisible (%s)" % (f, e))
            continue
        propre, n = _nettoyer(brut, litteraux)
        total += n
        etat = "%d occurrence(s)" % n if n else "propre"
        print("  %-46s %s" % (str(f), etat))
        if n and a.appliquer:
            sauv = f.with_suffix(f.suffix + ".avant_purge")
            shutil.copy2(f, sauv)
            f.write_text(propre, encoding="utf-8")
            print("      -> purge (copie d'origine : %s)" % sauv.name)

    print()
    print("  TOTAL : %d occurrence(s) de secret en clair." % total)
    if total and not a.appliquer:
        print("  Simulation uniquement. Ajoute --appliquer pour nettoyer.")
    if total and a.appliquer:
        print()
        print("  Les copies .avant_purge contiennent ENCORE les secrets.")
        print("  Supprime-les une fois le resultat verifie.")
    print()
    print("  RAPPEL : nettoyer les journaux ne desamorce pas une cle qui a")
    print("  fuite. Regenere-la chez le fournisseur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
