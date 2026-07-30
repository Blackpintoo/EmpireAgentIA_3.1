# -*- coding: utf-8 -*-
"""
tools/gen_legacy_guards.py — extrait VERBATIM la bande de gardes de
`execute_trade` telle qu'elle existait AVANT l'extraction P2, et la
transforme en fonction autonome exécutable.

But : disposer d'une référence d'origine réellement exécutable, pour
prouver par différentiel que le module `orchestrator/trade_guards.py`
décide exactement comme le code d'origine. La référence n'est pas
retapée : elle est copiée octet pour octet depuis le commit indiqué.

Usage :
    python tools/gen_legacy_guards.py <commit> > tests/_legacy_guards_ref.py

Le commit par défaut est celui qui précède l'extraction (P1).
"""
import subprocess
import sys

COMMIT_DEFAUT = "dff6ec7"
FICHIER = "orchestrator/orchestrator.py"

# Bande verbatim : du premier garde (fenêtre profil) à la fin du
# session filter, juste avant le bloc MTF mort (`if False:`).
MARQUEUR_DEBUT = "        # Re-vérifie la fenêtre au moment de l'exécution"
MARQUEUR_FIN = '            logger.debug(f"[SESSION_FILTER] Erreur: {e}")'

ENTETE = '''# -*- coding: utf-8 -*-
# FICHIER GENERE — NE PAS EDITER A LA MAIN.
# Produit par tools/gen_legacy_guards.py depuis le commit %s.
# Contient la bande de gardes de execute_trade telle qu'elle etait AVANT
# l'extraction P2, copiee verbatim, rendue executable pour le test
# differentiel tests/test_trade_guards_equivalence.py.
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def legacy_guards(self, signal, _mt5, logger, broker_to_canon, canon_to_broker,
                  get_qr_cooldown, BLACKLIST_OVERRIDE_WHITELIST):
    """Renvoie False si un garde bloque, sinon un dict des variables cles."""
    symbol = self.symbol
'''

PIED = '''
    return {
        "verdict": True,
        "sig": sig,
        "symbol": symbol,
        "broker_symbol": broker_symbol,
        "entry": entry,
        "lots": lots,
        "sl": sl,
        "tp": tp,
        "action": action,
        "current_hour_utc": current_hour_utc,
        "blocked_hours": blocked_hours,
        "allowed_hours": allowed_hours,
        "HARD_MIN_SCORE": HARD_MIN_SCORE,
        "score_agr": score_agr,
        "confluence": confluence,
        "tracker_vote": tracker_vote,
    }
'''


def main() -> int:
    commit = sys.argv[1] if len(sys.argv) > 1 else COMMIT_DEFAUT
    src = subprocess.run(
        ["git", "show", "%s:%s" % (commit, FICHIER)],
        stdout=subprocess.PIPE, check=True,
    ).stdout.decode("utf-8")
    # Le depot stocke ce fichier en CRLF : on normalise avant decoupage.
    lignes = src.replace("\r\n", "\n").split("\n")

    try:
        i0 = lignes.index(MARQUEUR_DEBUT)
        i1 = lignes.index(MARQUEUR_FIN)
    except ValueError as e:
        print("Marqueur introuvable dans %s : %s" % (commit, e), file=sys.stderr)
        return 1

    # La bande vit dans un corps de methode (indentation 8) ; la reference
    # est une fonction de module (indentation 4). On retire exactement 4
    # espaces a chaque ligne non vide : aucune autre transformation.
    bande = []
    for ligne in lignes[i0:i1 + 1]:
        if ligne.strip() == "":
            bande.append("")
        else:
            assert ligne.startswith("    "), "indentation inattendue: %r" % ligne
            bande.append(ligne[4:])

    sys.stdout.write(ENTETE % commit)
    sys.stdout.write("\n".join(bande))
    sys.stdout.write("\n")
    sys.stdout.write(PIED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
