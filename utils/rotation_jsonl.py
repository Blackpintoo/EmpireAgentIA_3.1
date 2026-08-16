# -*- coding: utf-8 -*-
"""
utils/rotation_jsonl.py — borner la taille des journaux JSONL d'analyse.

AJOUT 2026-08-16.

Le problème
-----------
`data/agents_snap.jsonl` est ouvert en ajout à chaque décision, sans aucune
borne. Il atteignait 530 Mo au 16/08. Deux conséquences :

  - le disque grossit indéfiniment, en silence ;
  - le fichier devient inexploitable — on ne charge pas 530 Mo pour lire les
    trente dernières décisions.

Ce module est le préalable à l'enrichissement des snapshots : ajouter des
champs explicatifs à un fichier déjà non borné aurait accéléré la dérive.

Ce que fait la rotation
-----------------------
Avant écriture, si le fichier dépasse `taille_max`, il devient `.1`, l'ancien
`.1` devient `.2`, etc. Au-delà de `conserver`, le plus ancien est supprimé.
C'est la rotation classique de logrotate, en une fonction.

Choix assumés
-------------
- On teste la taille AVANT l'écriture, pas après : un enregistrement peut donc
  dépasser légèrement la borne. Ça évite un second `stat` par écriture.
- Toute erreur est avalée. Ce journal sert au diagnostic ; il ne doit jamais
  faire échouer une décision de trading. C'est le même parti pris que
  `_log_agents_snapshot_jsonl`, qui enveloppe déjà tout dans un try/except.
- La rotation ne relit ni ne réécrit le contenu : ce sont des `rename`, donc
  une opération quasi instantanée quelle que soit la taille du fichier.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

# 50 Mo par fichier, 3 fichiers conservés → 200 Mo au total, plafond dur.
TAILLE_MAX_DEFAUT = 50 * 1024 * 1024
CONSERVER_DEFAUT = 3


def rouler_si_besoin(
    chemin: Union[str, Path],
    taille_max: int = TAILLE_MAX_DEFAUT,
    conserver: int = CONSERVER_DEFAUT,
) -> bool:
    """
    Fait tourner `chemin` s'il dépasse `taille_max`.

    Renvoie True si une rotation a eu lieu, False sinon (y compris en cas
    d'erreur — l'appelant ne doit jamais avoir à s'en soucier).
    """
    try:
        p = Path(chemin)
        if taille_max <= 0 or conserver < 0:
            return False
        if not p.exists() or p.stat().st_size < taille_max:
            return False

        # Le plus ancien d'abord, sinon on écrase en cascade.
        plus_ancien = p.with_name(p.name + ".%d" % conserver)
        if conserver >= 1 and plus_ancien.exists():
            try:
                plus_ancien.unlink()
            except Exception:
                return False

        for i in range(conserver - 1, 0, -1):
            src = p.with_name(p.name + ".%d" % i)
            if src.exists():
                os.replace(src, p.with_name(p.name + ".%d" % (i + 1)))

        if conserver >= 1:
            os.replace(p, p.with_name(p.name + ".1"))
        else:
            # conserver=0 : on ne garde aucun historique.
            p.unlink()
        return True
    except Exception:
        return False
