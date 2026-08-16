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
from typing import Optional, Union

# 50 Mo par fichier, 3 fichiers conservés → 200 Mo au total, plafond dur.
TAILLE_MAX_DEFAUT = 50 * 1024 * 1024
CONSERVER_DEFAUT = 3


def _depuis_env(nom: str, defaut: int) -> int:
    """
    Lit un entier d'environnement, en retombant sur le défaut si absurde.

    FIX 2026-08-16 : la première version prenait un `facteur` qu'elle
    n'appliquait QUE sur la valeur lue, pas sur le défaut. Sans variable
    d'environnement, le seuil valait donc 50 octets au lieu de 50 Mo, et le
    journal tournait à chaque écriture. Le facteur est désormais appliqué par
    l'appelant, sur les deux branches à la fois.
    """
    try:
        brut = os.environ.get(nom)
        if brut is None or str(brut).strip() == "":
            return defaut
        v = int(float(str(brut).strip()))
        return v if v >= 0 else defaut
    except Exception:
        return defaut


def rouler_si_besoin(
    chemin: Union[str, Path],
    taille_max: Optional[int] = None,
    conserver: Optional[int] = None,
) -> bool:
    """
    Fait tourner `chemin` s'il dépasse `taille_max`.

    Renvoie True si une rotation a eu lieu, False sinon (y compris en cas
    d'erreur — l'appelant ne doit jamais avoir à s'en soucier).

    FIX 2026-08-16 : les seuils sont lus À CHAQUE APPEL, depuis
    `EMPIRE_SNAP_MAX_MO` et `EMPIRE_SNAP_CONSERVER`. La première version les
    figeait comme valeurs par défaut de paramètres, donc évaluées une seule
    fois à l'import : impossible à régler en exploitation, et impossible à
    prouver en conditions réelles autrement qu'en écrivant 50 Mo. C'est la
    vérification de bout en bout qui l'a fait apparaître, pas la suite de
    tests — celle-ci passait les seuils explicitement et ne touchait donc
    jamais au chemin réellement emprunté en production.
    """
    try:
        if taille_max is None:
            taille_max = _depuis_env(
                "EMPIRE_SNAP_MAX_MO", TAILLE_MAX_DEFAUT // (1024 * 1024)
            ) * 1024 * 1024
        if conserver is None:
            conserver = _depuis_env("EMPIRE_SNAP_CONSERVER", CONSERVER_DEFAUT)

        p = Path(chemin)
        if taille_max <= 0 or conserver < 0:
            return False
        # FIX 2026-08-16 : `is_file()` et pas `exists()`. Sur un repertoire,
        # os.replace() reussit — la rotation aurait renomme le dossier.
        if not p.is_file() or p.stat().st_size < taille_max:
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
