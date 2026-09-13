# -*- coding: utf-8 -*-
"""
utils/journal_cycles.py — une ligne par cycle, inconditionnellement.

AJOUT 2026-09-13 (etape 1 de la recherche d'edge).

Le probleme qu'il resout
------------------------
`data/agents_snap.jsonl` n'est ecrit qu'APRES qu'une direction a ete decidee :
`context="executed"` rejoue le contexte qui a produit un ordre, `context=
"proposed"` n'existe qu'une fois une proposition formee. Mesure du 13/09 sur
les 33 trades appariables : 0 vote « contre », 0 « WAIT », sur les cinq
agents. Le fichier est conditionne sur l'accord des agents — une selection sur
la variable expliquee. Aucune mesure de pouvoir predictif n'y survit.

Ce journal-ci ecrit une ligne a CHAQUE cycle, quel qu'en soit le sort :
proposition, WAIT, refus par un garde, sortie anticipee, exception. C'est la
seule facon d'observer les cas ou un agent votait contre, ou ou personne ne
votait.

Format
------
CSV a colonnes fixes plutot que JSONL. Mesure sur une ligne representative :
75 octets en CSV contre 142 en JSONL positionnel et 250 en JSONL verbeux. A
12 symboles x 3 TF x 720 cycles/jour, cela fait 1,94 Mo/jour contre 3,68 et
6,48. Le contenu est strictement tabulaire — aucun sous-dictionnaire, comme
demande — donc le CSV ne perd rien et divise la place par deux. Le prix a
payer est un format different de agents_snap.jsonl, qui lui ne change pas.

Rotation : 48 Mo x 4 = 192 Mo, soit environ 99 jours a 7j/7 et 139 jours a
5j/7 (les indices et le forex ne cotent pas le week-end). L'objectif de 90
jours est donc tenu meme sous l'hypothese la plus defavorable.

Le prix de reference
--------------------
La demande portait sur « le close du cycle sur le TF concerne ». Ce close
n'existe nulle part dans ce que le cycle a deja calcule : `market` ne porte
qu'un prix instantane, `indicators` que des ATR par TF. L'obtenir exigerait un
appel MT5 supplementaire, ce que la consigne interdit explicitement.

On ecrit donc `px`, le prix a l'instant de la decision, et `atr`, l'ATR du TF
concerne — tous deux deja calcules. Pour un contrefactuel c'est preferable au
close de la derniere bougie : on veut le prix au moment ou le vote a ete emis,
et l'ATR donne l'echelle pour normaliser en R le mouvement ulterieur.

Garanties
---------
Aucune fonction ne leve. Ce journal est un instrument de mesure ; il ne doit
jamais faire echouer un cycle de trading. Il n'influence aucune decision : il
transcrit ce que le cycle a deja calcule, rien de plus.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.rotation_jsonl import rouler_si_besoin
except Exception:                                    # pragma: no cover
    def rouler_si_besoin(*_a, **_k):                 # type: ignore
        return False

NOM_FICHIER = "cycles.csv"

# 48 Mo x 4 fichiers = 192 Mo -> ~99 jours a 7j/7, ~139 jours a 5j/7.
TAILLE_MAX = 48 * 1024 * 1024
CONSERVER = 4

# Ordre FIGE des agents dans la colonne `votes`. Toute modification de cette
# liste change la signification des lignes deja ecrites : ne pas y toucher
# sans changer aussi le nom du fichier.
AGENTS = ("structure", "smc", "swing", "technical", "scalping", "news")

COLONNES = ["ts_utc", "symbole", "tf", "votes", "score_L", "score_S",
            "confluence", "direction", "garde", "px", "atr"]

_CODE = {"LONG": "L", "SHORT": "S", "WAIT": "W"}
_VERROU = threading.Lock()

# Dernier garde declenche, par symbole. Rempli par l'orchestrateur au moment ou
# un garde refuse, lu puis efface a la fin du cycle. Un dictionnaire de module
# parce que les gardes sont journalises depuis une fonction de module, loin de
# l'instance : le detour evite de toucher a la vingtaine de points d'appel.
_DERNIER_GARDE: Dict[str, str] = {}


def noter_garde(symbole: str, nom: str) -> None:
    """Memorise le garde qui vient de refuser, pour le cycle en cours."""
    try:
        if symbole and nom:
            _DERNIER_GARDE[str(symbole)] = str(nom)[:40]
    except Exception:
        pass


def reprendre_garde(symbole: str) -> str:
    """Renvoie le garde note pour ce symbole et l'efface."""
    try:
        return _DERNIER_GARDE.pop(str(symbole), "") or ""
    except Exception:
        return ""


def code_vote(v: Any) -> str:
    """LONG->L, SHORT->S, WAIT->W, absent->'-'."""
    try:
        if v is None:
            return "-"
        s = str(v).strip().upper()
        if not s:
            return "-"
        return _CODE.get(s, "W")
    except Exception:
        return "-"


def votes_du_tf(per_tf_signals: Any, global_signals: Any, tf: str) -> str:
    """
    Chaine positionnelle d'un caractere par agent, dans l'ordre de AGENTS.

    On prend le vote du TF quand l'agent en a un ; sinon son vote global
    (c'est le cas de `news`, qui n'est jamais ventile par TF) ; sinon '-'.
    """
    out: List[str] = []
    ptf = per_tf_signals if isinstance(per_tf_signals, dict) else {}
    gl = global_signals if isinstance(global_signals, dict) else {}
    for agent in AGENTS:
        v = None
        try:
            m = ptf.get(agent)
            if isinstance(m, dict):
                v = m.get(tf)
            if v is None:
                v = gl.get(agent)
        except Exception:
            v = None
        out.append(code_vote(v))
    return "".join(out)


def _nb(x: Any, defaut: str = "") -> str:
    try:
        if x is None:
            return defaut
        return "%.3f" % float(x)
    except Exception:
        return defaut


def lignes_du_cycle(cycle: Dict[str, Any], tfs: Any) -> List[List[str]]:
    """
    Traduit l'etat collecte pendant un cycle en une ligne par timeframe.

    Un cycle sorti tres tot (cooldown, garde quotidien) n'a pas de vote : on
    ecrit quand meme une ligne par TF, avec des votes a '-'. C'est precisement
    ce qu'on veut pouvoir compter.
    """
    try:
        c = cycle or {}
        sym = str(c.get("symbole") or "")
        ts = str(c.get("ts_utc") or "")
        liste_tf = [str(t) for t in (tfs or []) if t] or ["?"]
        ptf = c.get("per_tf_signals")
        gl = c.get("global_signals")
        ind = c.get("indicators") if isinstance(c.get("indicators"), dict) else {}
        px = c.get("px")
        sL, sS = c.get("score_L"), c.get("score_S")
        cf = c.get("confluence")
        direction = code_vote(c.get("direction") or "WAIT")
        garde = str(c.get("garde") or "")[:40].replace(",", ";").replace("\n", " ")

        lignes: List[List[str]] = []
        for tf in liste_tf:
            atr = None
            try:
                atr = ind.get("ATR_%s" % tf)
            except Exception:
                atr = None
            lignes.append([
                ts, sym, tf, votes_du_tf(ptf, gl, tf),
                _nb(sL), _nb(sS), _nb(cf), direction, garde, _nb(px), _nb(atr),
            ])
        return lignes
    except Exception:
        return []


def chemin_journal() -> Path:
    """Chemin d'ecriture, cloisonne par compte comme les autres donnees."""
    try:
        from utils.account_scope import chemin_donnees
        return Path(chemin_donnees(NOM_FICHIER))
    except Exception:
        p = Path("data") / NOM_FICHIER
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return p


def ecrire(lignes: List[List[str]], chemin: Optional[Path] = None) -> int:
    """
    Ajoute les lignes au journal. Renvoie le nombre de lignes ecrites.

    Ne leve jamais : en cas de probleme d'ecriture on renvoie 0 et le cycle
    continue. Perdre une ligne de mesure est sans consequence ; interrompre un
    cycle pour cette raison serait absurde.
    """
    if not lignes:
        return 0
    try:
        p = Path(chemin) if chemin is not None else chemin_journal()
        with _VERROU:
            rouler_si_besoin(p, taille_max=TAILLE_MAX, conserver=CONSERVER)
            neuf = not p.exists() or p.stat().st_size == 0
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            with p.open("a", encoding="utf-8", newline="") as fh:
                if neuf:
                    fh.write(",".join(COLONNES) + "\n")
                for l in lignes:
                    fh.write(",".join("" if v is None else str(v) for v in l) + "\n")
        return len(lignes)
    except Exception:
        return 0
