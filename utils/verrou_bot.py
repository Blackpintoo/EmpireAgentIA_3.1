# -*- coding: utf-8 -*-
"""
utils/verrou_bot.py — savoir si LE BOT tourne, et pas « un python quelconque ».

AJOUT 2026-08-02.

Le problème
-----------
`tools/purger_secrets_logs.py` refusait d'agir dès qu'un `python.exe` figurait
dans `tasklist`. Ce signal est bien trop large :

  - il a bloqué la purge appelée depuis un test, puisque pytest EST un
    python.exe — le garde se déclenchait sur le processus qui l'interrogeait ;
  - en production, un notebook Jupyter, un IDE, un script d'analyse ou même un
    autre outil de ce dépôt aurait produit le même faux positif ;
  - et il ne dit rien du cas inverse : un bot lancé depuis un exécutable
    renommé serait passé inaperçu.

Ce que fait ce module
---------------------
Le bot dépose `data/bot.pid` à son démarrage : son PID, l'heure de démarrage
et le point d'entrée. Les outils interrogent ce fichier plutôt que la liste
des processus. Un verrou dont le PID n'existe plus est signalé comme périmé et
ignoré — un arrêt brutal ne doit pas bloquer les outils pour toujours.

Limite assumée : après un arrêt brutal, le système peut réattribuer le PID à
un autre processus. Le verrou serait alors considéré comme actif à tort. Le
risque est faible et le coût d'une erreur est nul (l'outil demande simplement
de fermer le bot), là où le faux positif précédent était systématique.
"""
from __future__ import annotations

import atexit
import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

CHEMIN_VERROU = Path("data") / "bot.pid"


def _processus_vivant(pid: int) -> bool:
    """Vrai si ce PID correspond à un processus en cours."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import subprocess
            sortie = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
            ).stdout.decode("utf-8", "replace")
            return str(pid) in sortie
        except Exception:
            # Dans le doute, on se déclare vivant : mieux vaut refuser une
            # purge à tort que réécrire un journal ouvert en écriture.
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # existe, mais appartient à un autre utilisateur
    except Exception:
        return True


def poser_verrou(point_entree: str = "?", chemin: Optional[Path] = None) -> Optional[Path]:
    """
    Déclare que le bot tourne. À appeler une fois, au démarrage.
    Le verrou est retiré automatiquement à la sortie du processus.
    """
    p = Path(chemin or CHEMIN_VERROU)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "pid": os.getpid(),
            "demarre_le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "point_entree": point_entree,
            "repertoire": os.getcwd(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return None
    atexit.register(lever_verrou, p)
    return p


def lever_verrou(chemin: Optional[Path] = None) -> None:
    p = Path(chemin or CHEMIN_VERROU)
    try:
        if p.exists():
            contenu = json.loads(p.read_text(encoding="utf-8") or "{}")
            # On ne retire que SON PROPRE verrou : deux processus concurrents
            # ne doivent pas se marcher dessus.
            if int(contenu.get("pid", -1)) == os.getpid():
                p.unlink()
    except Exception:
        pass


def bot_actif(chemin: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Renvoie (actif, explication).

    - pas de fichier          -> (False, "aucun verrou")
    - PID mort                -> (False, "verrou périmé …") et le fichier est retiré
    - PID vivant              -> (True, "bot en cours, PID …")
    """
    p = Path(chemin or CHEMIN_VERROU)
    if not p.exists():
        return False, "aucun verrou : le bot n'est pas declare en cours d'execution"
    try:
        contenu = json.loads(p.read_text(encoding="utf-8") or "{}")
        pid = int(contenu.get("pid", -1))
    except Exception:
        return False, "verrou illisible, ignore"

    if pid == os.getpid():
        # Le processus courant EST le bot : il sait ce qu'il fait.
        return False, "le verrou appartient au processus courant"

    if _processus_vivant(pid):
        return True, ("bot en cours (PID %d, demarre le %s via %s)"
                      % (pid, contenu.get("demarre_le", "?"),
                         contenu.get("point_entree", "?")))

    try:
        p.unlink()
    except Exception:
        pass
    return False, ("verrou perime (PID %d absent) — retire. Le bot s'est "
                   "probablement arrete brutalement." % pid)
