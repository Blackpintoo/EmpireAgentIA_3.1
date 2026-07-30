# -*- coding: utf-8 -*-
"""
utils/account_scope.py — cloisonnement des données de performance par compte MT5.

AJOUT 2026-07-30 (P5).

Le problème
-----------
`data/performance/tracker_*.json`, `data/trade_outcomes.csv` et
`data/deals_history.csv` ne portaient aucune trace du compte qui les avait
produits. Quand un compte est fermé et remplacé — ce qui est arrivé en juillet
2026 — l'historique de l'ancien compte reste en place et continue d'alimenter :

  - `tracker_vote`, donc le garde de contradiction du tracker ;
  - `_get_adaptive_score_boost`, donc le seuil de score effectif ;
  - `should_allow_live`, donc l'autorisation de trader en réel.

Autrement dit, les décisions du compte courant étaient conditionnées par les
résultats d'un compte qui n'existe plus, sur un broker éventuellement différent,
avec un levier et une taille de contrat éventuellement différents.

La solution
-----------
Un répertoire par compte : `data/performance/compte_25832276/tracker_BTCUSD.json`.

Aucune migration automatique : rien dans les fichiers existants ne permet de
savoir quel compte les a produits, et deviner reviendrait à réintroduire
exactement le problème. Les fichiers hérités sont laissés en place, ignorés, et
signalés une fois dans les logs. Pour les rattacher volontairement à un compte,
`tools/adopter_historique_compte.py` fait la copie de façon explicite.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_INCONNU = "inconnu"
_cache: Optional[str] = None
_deja_signale = False


def _depuis_config() -> Optional[str]:
    """Dernier recours : lire le numéro de compte dans la configuration."""
    try:
        from utils.config import load_config  # import tardif : évite un cycle
        cfg = load_config() or {}
        for chemin in (("mt5", "login"), ("mt5", "account"), ("mt5", "compte")):
            noeud = cfg
            for cle in chemin:
                noeud = (noeud or {}).get(cle) if isinstance(noeud, dict) else None
            if noeud:
                return str(noeud)
    except Exception:
        pass
    return None


def numero_compte(force: bool = False) -> str:
    """
    Numéro du compte MT5 courant, sous forme de chaîne sûre pour un nom de
    dossier. Renvoie "inconnu" si aucune source ne le fournit — dans ce cas les
    données sont cloisonnées sous `compte_inconnu`, jamais mélangées avec un
    compte identifié.
    """
    global _cache
    if _cache is not None and not force:
        return _cache
    brut = (os.environ.get("MT5_ACCOUNT")
            or os.environ.get("MT5_LOGIN")
            or _depuis_config()
            or _INCONNU)
    propre = re.sub(r"[^A-Za-z0-9_-]", "", str(brut).strip()) or _INCONNU
    _cache = propre
    return propre


def repertoire_compte(base: Path | str = "data") -> Path:
    return Path(base) / ("compte_%s" % numero_compte())


def chemin_scope(chemin: Path | str) -> Path:
    """
    Insère le répertoire du compte juste avant le nom de fichier.

        data/performance/tracker_BTCUSD.json
        -> data/performance/compte_25832276/tracker_BTCUSD.json
    """
    p = Path(chemin)
    return p.parent / ("compte_%s" % numero_compte()) / p.name


def chemin_donnees(nom: str, base: Path | str = "data") -> Path:
    """
    Chemin d'ECRITURE d'un fichier de donnees, cloisonne par compte.
        chemin_donnees("trade_outcomes.csv")
        -> data/compte_25832276/trade_outcomes.csv
    """
    dossier = repertoire_compte(base)
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return dossier / nom


def chemin_lecture(nom: str, base: Path | str = "data") -> Path:
    """
    Chemin de LECTURE pour les outils de reporting : la version du compte si
    elle existe, sinon l'ancien emplacement non cloisonne. Ce repli est
    volontairement reserve a la lecture d'analyse — il ne doit PAS servir a
    alimenter une decision de trading, sans quoi l'historique d'un compte
    ferme influencerait a nouveau le compte courant.
    """
    scope = repertoire_compte(base) / nom
    if scope.exists():
        return scope
    return Path(base) / nom


def signaler_heritage(chemins, logger_obj=None) -> None:
    """
    Signale UNE FOIS que des fichiers non rattachés à un compte existent et
    sont ignorés. Sans ce message, l'utilisateur croirait à une perte de
    données alors qu'il s'agit d'un cloisonnement volontaire.
    """
    global _deja_signale
    if _deja_signale:
        return
    orphelins = [str(c) for c in chemins if Path(c).exists()]
    if not orphelins:
        return
    _deja_signale = True
    msg = ("[COMPTE] Historique non rattache a un compte detecte et IGNORE "
           "pour le compte %s : %s. Ces donnees proviennent peut-etre d'un "
           "compte ferme ; les reprendre fausserait les seuils adaptatifs et "
           "le live guard. Pour les rattacher volontairement : "
           "python tools/adopter_historique_compte.py"
           % (numero_compte(), ", ".join(orphelins[:6])))
    if logger_obj is not None:
        try:
            logger_obj.warning(msg)
            return
        except Exception:
            pass
    print(msg)


def reinitialiser_cache() -> None:
    """Utilisé par les tests."""
    global _cache, _deja_signale
    _cache = None
    _deja_signale = False
