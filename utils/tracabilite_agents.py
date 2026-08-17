# -*- coding: utf-8 -*-
"""
utils/tracabilite_agents.py — garder POURQUOI un agent a vote, pas seulement
dans quel sens.

AJOUT 2026-08-16.

Le problème
-----------
NewsAgent, SentimentAgent et FundamentalAgent renvoient un dictionnaire riche :

    news      → signal, intensity, bull_score, bear_score, examples, v2_analysis,
                method, et parfois reason="MACRO_BLOCK"
    sentiment → signal, agg_score, google_score, trend, sous-scores FG/Twitter
    fundamental → signal, et le detail de l'evenement declencheur

L'orchestrateur n'en gardait qu'une chose :

    s = _norm(out_g.get("signal"))      # "LONG" | "SHORT" | ""

Tout le reste etait calcule puis jete dans la meme milliseconde. Consequence
concrete : devant un trade perdant, impossible de savoir POURQUOI news avait
vote LONG. Et un `signal: None` pour cause de MACRO_BLOCK etait indiscernable
d'une absence pure et simple d'actualite.

Ce que fait ce module
---------------------
Il resume chaque sortie d'agent en un dictionnaire borne, destine au seul
journal `data/agents_snap.jsonl`. Il n'entre PAS dans la chaine de vote : le
score composite et la direction agregee ne le voient jamais.

Bornes
------
Sans borne, ces resumes gonfleraient le journal (deja sous rotation depuis le
commit precedent, mais autant ne pas la declencher pour rien). Trois titres
par camp, 120 caracteres chacun, profondeur fixe.

Aucune fonction ne leve. Une tracabilite qui casserait une decision de trading
serait pire que pas de tracabilite du tout.
"""
from __future__ import annotations

from typing import Any, Dict, List

LONGUEUR_TITRE = 120
NB_EXEMPLES = 3


def _texte(v: Any, longueur: int = LONGUEUR_TITRE) -> str:
    try:
        s = str(v).replace("\n", " ").replace("\r", " ").strip()
        return s[:longueur]
    except Exception:
        return ""


def _nombre(v: Any):
    try:
        if v is None or isinstance(v, bool):
            return None
        return round(float(v), 6)
    except Exception:
        return None


def _titres(v: Any) -> List[str]:
    """Accepte une liste de chaines ou de dicts {'title': ...}."""
    out: List[str] = []
    try:
        for item in list(v or [])[:NB_EXEMPLES]:
            if isinstance(item, dict):
                t = _texte(item.get("title") or item.get("titre") or "")
                sc = _nombre(item.get("score"))
                out.append("%s (%s)" % (t, sc) if sc is not None else t)
            else:
                out.append(_texte(item))
    except Exception:
        return out
    return [t for t in out if t]


def resumer_news(sortie: Any) -> Dict[str, Any]:
    if not isinstance(sortie, dict):
        return {}
    r: Dict[str, Any] = {}
    try:
        r["signal"] = _texte(sortie.get("signal") or "", 12) or None
        r["intensity"] = _nombre(sortie.get("intensity"))
        r["bull_score"] = _nombre(sortie.get("bull_score"))
        r["bear_score"] = _nombre(sortie.get("bear_score"))
        r["method"] = _texte(sortie.get("method") or "", 20) or None
        # Le champ qui manquait le plus : distingue "pas d'actualite" de
        # "actualite bloquee par un evenement macro".
        if sortie.get("reason"):
            r["reason"] = _texte(sortie.get("reason"), 40)

        ex = sortie.get("examples")
        if isinstance(ex, dict):
            bull, bear = _titres(ex.get("bull")), _titres(ex.get("bear"))
            if bull or bear:
                r["examples"] = {"bull": bull, "bear": bear}

        v2 = sortie.get("v2_analysis")
        if isinstance(v2, dict):
            r["v2"] = {
                "signal": _texte(v2.get("signal") or "", 12) or None,
                "score": _nombre(v2.get("score")),
                "confidence": _nombre(v2.get("confidence")),
                "level": _texte(v2.get("level") or "", 20) or None,
                "bullish_count": _nombre(v2.get("bullish_count")),
                "bearish_count": _nombre(v2.get("bearish_count")),
                "relevant_items": _nombre(v2.get("relevant_items")),
                "top_bullish": _titres(v2.get("top_bullish")),
                "top_bearish": _titres(v2.get("top_bearish")),
            }
    except Exception:
        pass
    return {k: v for k, v in r.items() if v not in (None, {}, [])}


def resumer_sentiment(sortie: Any) -> Dict[str, Any]:
    if not isinstance(sortie, dict):
        return {}
    r: Dict[str, Any] = {}
    try:
        r["signal"] = _texte(sortie.get("signal") or "", 12) or None
        r["agg_score"] = _nombre(sortie.get("agg_score"))
        r["google_score"] = _nombre(sortie.get("google_score"))
        r["google_value"] = _nombre(sortie.get("google_value"))
        r["trend"] = _texte(sortie.get("trend") or "", 20) or None
        if sortie.get("reason"):
            r["reason"] = _texte(sortie.get("reason"), 40)
        for cle in ("fear_greed", "fg", "twitter"):
            sous = sortie.get(cle)
            if isinstance(sous, dict):
                r[cle] = {k: _nombre(v) for k, v in list(sous.items())[:6]
                          if _nombre(v) is not None}
            elif sous is not None and _nombre(sous) is not None:
                r[cle] = _nombre(sous)
    except Exception:
        pass
    return {k: v for k, v in r.items() if v not in (None, {}, [])}


def resumer_fundamental(sortie: Any) -> Dict[str, Any]:
    if not isinstance(sortie, dict):
        return {}
    r: Dict[str, Any] = {}
    try:
        r["signal"] = _texte(sortie.get("signal") or "", 12) or None
        for cle in ("score", "impact", "intensity", "surprise", "deviation"):
            n = _nombre(sortie.get(cle))
            if n is not None:
                r[cle] = n
        for cle in ("reason", "event", "evenement", "currency", "devise"):
            t = _texte(sortie.get(cle) or "", 80)
            if t:
                r[cle] = t
    except Exception:
        pass
    return {k: v for k, v in r.items() if v not in (None, {}, [])}
