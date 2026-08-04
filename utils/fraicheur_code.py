# -*- coding: utf-8 -*-
"""
utils/fraicheur_code.py — le code sur le disque est-il celui qui tourne ?

AJOUT 2026-08-04.

Le defaut, observe en production
--------------------------------
Le 2 aout, `connectors/finnhub_client.py` a ete reecrit par un `git checkout`
a 12:26:27, quatre secondes avant que le bot ne journalise son demarrage.
Le processus avait deja importe l'ancienne version du module ; il l'a gardee
en memoire pendant six heures. Resultat : la cle Finnhub a continue de fuir en
clair a 14:04, 16:04 et 18:04, alors que le correctif etait sur le disque et
que le fichier `.pyc` recompile, lui, etait a jour. Rien dans les journaux ne
signalait l'ecart — j'ai mis une heure a le comprendre, et j'ai d'abord conclu
a tort que le correctif ne fonctionnait pas.

Ce module ne fait PAS doublon avec startup_selftest
---------------------------------------------------
Les deux repondent a des questions differentes, et c'est la confusion entre
elles qui a produit un rapport contradictoire :

  - `utils/startup_selftest.py` demande : « le code a-t-il change depuis la
    derniere VALIDATION reussie ? » Il compare une empreinte de contenu a
    `data/selftest_state.json`. Il protege contre le demarrage d'un code non
    teste. Ce garde-fou existe depuis le 30/07.

  - ce module-ci demande : « le code a-t-il change depuis le DEMARRAGE de CE
    processus ? » Il compare les dates de modification a l'heure de demarrage.
    Il protege contre un processus qui execute, en memoire, autre chose que ce
    qu'on lit sur le disque. Ce garde-fou n'existait pas.

Un code peut etre parfaitement valide (selftest vert) ET perime en memoire :
c'est exactement ce qui s'est passe le 2 aout.

Limite assumee
--------------
L'heure de reference est prise par `main.py` a sa toute premiere ligne, avant
tout import du depot. Les seuls modules non couverts sont donc `os`, `sys` et
`time` de la bibliotheque standard. Un fichier ecrit AVANT cette ligne mais
apres le veritable demarrage de l'interpreteur (quelques millisecondes)
passerait inapercu ; le cout d'un tel raté est nul face au faux positif
systematique qu'une marge de securite introduirait.
"""
from __future__ import annotations

import os
import sys
import time
from typing import List, Optional, Sequence, Tuple

# Meme périmètre que l'empreinte du selftest : on réutilise sa liste pour que
# les deux garde-fous ne puissent pas diverger sur ce qu'ils considèrent
# comme « le code ».
from utils.startup_selftest import _iter_python_files  # noqa: F401

CODE_SORTIE = 4
_VAR_CONTOURNEMENT = "EMPIRE_SKIP_FRAICHEUR"


def fichiers_modifies_depuis(t_reference: float,
                             racine: str,
                             fichiers: Optional[Sequence[str]] = None
                             ) -> List[Tuple[str, float]]:
    """
    Renvoie [(chemin_relatif, mtime), ...] pour les .py dont la date de
    modification est POSTERIEURE a `t_reference`, triés du plus récent au
    plus ancien.

    Un fichier illisible ou disparu est ignoré : il ne s'agit pas de dire si
    le dépôt est sain, seulement si quelque chose a bougé sous nos pieds.
    """
    sortie: List[Tuple[str, float]] = []
    for chemin in (fichiers if fichiers is not None else _iter_python_files(racine)):
        try:
            mtime = os.path.getmtime(chemin)
        except OSError:
            continue
        if mtime > t_reference:
            rel = os.path.relpath(chemin, racine).replace("\\", "/")
            sortie.append((rel, mtime))
    sortie.sort(key=lambda c: c[1], reverse=True)
    return sortie


def _horodatage(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def verifier_fraicheur_code(racine: str,
                            t_demarrage: float,
                            logger_obj=None,
                            sortir: bool = True) -> List[Tuple[str, float]]:
    """
    Refuse de continuer si du code Python a été modifié après le démarrage du
    processus — le module en mémoire n'est alors plus celui du disque.

    Renvoie la liste des fichiers en cause (vide si tout va bien).
    `sortir=False` permet aux tests et aux outils d'inspecter sans quitter.
    """
    def _dire(msg: str, erreur: bool = False) -> None:
        if logger_obj is not None:
            try:
                (logger_obj.error if erreur else logger_obj.info)(msg)
                return
            except Exception:
                pass
        print(msg, file=sys.stderr if erreur else sys.stdout, flush=True)

    divergents = fichiers_modifies_depuis(t_demarrage, racine)

    if not divergents:
        _dire("[FRAICHEUR] OK — aucun fichier .py modifié depuis le démarrage "
              "(%s)." % _horodatage(t_demarrage))
        return []

    contourne = os.environ.get(_VAR_CONTOURNEMENT, "").strip() in ("1", "true", "True", "yes")

    _dire("=" * 70, erreur=True)
    _dire("[FRAICHEUR] CODE MODIFIE APRES LE DEMARRAGE DU PROCESSUS", erreur=True)
    _dire("=" * 70, erreur=True)
    _dire("Processus démarré à %s (PID %d)." % (_horodatage(t_demarrage), os.getpid()),
          erreur=True)
    _dire("%d fichier(s) .py sont plus récents que ce démarrage :" % len(divergents),
          erreur=True)
    for rel, mtime in divergents[:15]:
        _dire("    %s   (modifié %s, soit %+.1f s après le démarrage)"
              % (rel, _horodatage(mtime), mtime - t_demarrage), erreur=True)
    if len(divergents) > 15:
        _dire("    … et %d autre(s)." % (len(divergents) - 15), erreur=True)
    _dire("", erreur=True)
    _dire("Ces modules ont pu être importés dans leur version PRECEDENTE : ce", erreur=True)
    _dire("processus exécuterait alors un code différent de celui du disque,", erreur=True)
    _dire("sans qu'aucun journal ne le signale (cas du 2026-08-02, cle Finnhub).", erreur=True)
    _dire("", erreur=True)
    _dire("Relance simplement le bot — les fichiers sont maintenant en place.", erreur=True)
    _dire("Pour démarrer malgré tout (à tes risques) : définis %s=1"
          % _VAR_CONTOURNEMENT, erreur=True)

    if contourne:
        _dire("[FRAICHEUR] CONTOURNE via %s=1 — démarrage POURSUIVI avec un "
              "code potentiellement périmé en mémoire." % _VAR_CONTOURNEMENT,
              erreur=True)
        return divergents

    if sortir:
        sys.exit(CODE_SORTIE)
    return divergents
