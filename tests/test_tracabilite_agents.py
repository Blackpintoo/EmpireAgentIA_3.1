# -*- coding: utf-8 -*-
"""
Tests de la tracabilite des agents API (news / sentiment / fundamental).

AJOUT 2026-08-16.

Deux choses a prouver :
  1. les resumes sont bornes, complets, et ne levent jamais ;
  2. ils n'entrent PAS dans la chaine de vote — c'est la condition qui rendait
     ce correctif acceptable en production.
"""
import inspect
import json

import pytest

from utils.tracabilite_agents import (
    resumer_fundamental,
    resumer_news,
    resumer_sentiment,
)


# --------------------------------------------------------------- resumer_news
def test_news_conserve_les_scores_et_la_methode():
    r = resumer_news({
        "signal": "LONG", "intensity": 0.42, "bull_score": 3.5,
        "bear_score": 1.25, "method": "hybrid_v2",
        "examples": {"bull": ["ETF approuve"], "bear": []},
    })
    assert r["signal"] == "LONG"
    assert r["intensity"] == 0.42
    assert r["bull_score"] == 3.5
    assert r["bear_score"] == 1.25
    assert r["method"] == "hybrid_v2"
    assert r["examples"]["bull"] == ["ETF approuve"]


def test_news_distingue_macro_block_d_une_absence_d_actualite():
    """
    Le cas qui motivait le correctif : agents/news.py renvoie signal=None
    aussi bien quand il n'y a pas d'actualite que quand un evenement macro
    bloque. Dans le vote, les deux etaient identiques.
    """
    bloque = resumer_news({"signal": None, "intensity": 0.0,
                           "reason": "MACRO_BLOCK", "bull_score": 4.0,
                           "bear_score": 0.0})
    vide = resumer_news({"signal": None, "intensity": 0.0,
                         "bull_score": 0.0, "bear_score": 0.0})

    assert bloque["reason"] == "MACRO_BLOCK"
    assert "reason" not in vide
    assert bloque != vide
    # Le blocage conservait un vrai desequilibre haussier : information
    # totalement perdue jusqu'ici.
    assert bloque["bull_score"] == 4.0


def test_news_v2_est_aplati_et_borne():
    r = resumer_news({
        "signal": "SHORT",
        "v2_analysis": {
            "signal": "SHORT", "score": -0.7, "confidence": 0.81,
            "level": "BEARISH", "bullish_count": 1, "bearish_count": 6,
            "relevant_items": 12,
            "top_bearish": [{"title": "T" * 300, "source": "reuters", "score": -0.9}],
            "top_bullish": [],
        },
    })
    assert r["v2"]["confidence"] == 0.81
    assert r["v2"]["bearish_count"] == 6
    assert len(r["v2"]["top_bearish"]) == 1
    assert len(r["v2"]["top_bearish"][0]) <= 140      # titre borne + score


def test_titres_bornes_en_longueur_et_en_nombre():
    r = resumer_news({
        "signal": "LONG",
        "examples": {"bull": ["A" * 500] * 10, "bear": ["B" * 500] * 10},
    })
    assert len(r["examples"]["bull"]) == 3
    assert all(len(t) <= 120 for t in r["examples"]["bull"])


def test_champs_vides_absents_du_resume():
    """Un resume vide ne doit pas occuper de place dans le journal."""
    assert resumer_news({"signal": None}) == {}
    assert resumer_sentiment({"signal": None}) == {}
    assert resumer_fundamental({}) == {}


# ---------------------------------------------------------- resumer_sentiment
def test_sentiment_conserve_le_motif_non_crypto():
    r = resumer_sentiment({"signal": None, "agg_score": 0.0,
                           "trend": "disabled", "reason": "non_crypto"})
    assert r["trend"] == "disabled"
    assert r["reason"] == "non_crypto"


def test_sentiment_conserve_les_sous_scores():
    r = resumer_sentiment({
        "signal": "LONG", "agg_score": 0.33, "google_score": 0.2,
        "google_value": 61, "trend": "greed",
        "fear_greed": {"score": 72, "poids": 0.5, "texte": "ignore"},
    })
    assert r["agg_score"] == 0.33
    assert r["google_value"] == 61
    assert r["fear_greed"]["score"] == 72
    assert "texte" not in r["fear_greed"]          # non numerique, ecarte


# -------------------------------------------------------- resumer_fundamental
def test_fundamental_conserve_l_evenement():
    r = resumer_fundamental({"signal": "SHORT", "impact": 0.8,
                             "event": "US CPI y/y", "currency": "USD"})
    assert r["signal"] == "SHORT"
    assert r["impact"] == 0.8
    assert r["event"] == "US CPI y/y"


# ------------------------------------------------------------ robustesse dure
@pytest.mark.parametrize("resumeur", [resumer_news, resumer_sentiment, resumer_fundamental])
@pytest.mark.parametrize("entree", [
    None, "", 0, [], ["liste"], {"signal": object()},
    {"examples": "pas un dict"}, {"v2_analysis": ["pas un dict"]},
    {"intensity": float("nan")}, {"bull_score": "abc"},
])
def test_aucun_resumeur_ne_leve_jamais(resumeur, entree):
    """
    Ce code tourne dans la boucle de decision. Une exception ici couterait un
    cycle de trading pour une ligne de journal.
    """
    sortie = resumeur(entree)
    assert isinstance(sortie, dict)
    json.dumps(sortie)          # doit rester serialisable


def test_resume_reste_serialisable_et_compact():
    r = resumer_news({
        "signal": "LONG", "intensity": 1.0, "bull_score": 9.0, "bear_score": 2.0,
        "method": "hybrid_v2",
        "examples": {"bull": ["x" * 400] * 5, "bear": ["y" * 400] * 5},
        "v2_analysis": {"signal": "LONG", "score": 0.5, "confidence": 0.9,
                        "level": "BULLISH", "top_bullish": [{"title": "z" * 400}] * 9},
    })
    brut = json.dumps(r, ensure_ascii=False)
    # Borne large : l'objectif est d'exclure la derive, pas de compter les octets.
    assert len(brut) < 2500, "resume trop volumineux : %d octets" % len(brut)


# ------------------------------------------------- invariant : hors du vote
def test_gather_agent_signals_renvoie_toujours_le_meme_quadruplet():
    """
    Garde-fou architectural. La tracabilite est deposee sur
    self._tracabilite_agents, JAMAIS dans la valeur de retour : le score
    composite et la direction agregee ne doivent rien voir de nouveau.

    Si quelqu'un cable un jour ces resumes dans le retour, ce test tombe.
    """
    from orchestrator.orchestrator import Orchestrator

    src = inspect.getsource(Orchestrator._gather_agent_signals)
    # Seuls les `return` du corps de la methode (indentation 8) comptent :
    # les fonctions imbriquees (thunks, agent_enabled) sont plus profondes.
    retours = [l for l in src.splitlines()
               if l.startswith(" " * 8) and l[8:].startswith("return ")]
    assert retours, "aucun return de premier niveau trouve"
    for r in retours:
        assert r.strip() == "return per_tf_signals, global_signals, indicators, market", (
            "la valeur de retour de _gather_agent_signals a change : %r" % r.strip())

    assert "self._tracabilite_agents = tracabilite" in src


def test_tracabilite_n_est_jamais_versee_dans_les_signaux():
    """
    La cle 'tracabilite' des thunks ne doit alimenter ni global_signals, ni
    per_tf_signals, ni indicators.
    """
    from orchestrator.orchestrator import Orchestrator

    src = inspect.getsource(Orchestrator._gather_agent_signals)
    for ligne in src.splitlines():
        if "tracabilite" not in ligne or ligne.strip().startswith("#"):
            continue
        for interdit in ("global_signals", "per_tf_signals", "indicators."):
            assert interdit not in ligne, (
                "la tracabilite touche %s : %s" % (interdit, ligne.strip()))


def test_snapshot_ecrit_agents_detail(tmp_path, monkeypatch):
    """Preuve de bout en bout : le resume atterrit bien dans le JSONL."""
    from orchestrator.orchestrator import Orchestrator

    monkeypatch.chdir(tmp_path)
    o = object.__new__(Orchestrator)
    o.symbol = "BTCUSD"
    o._tracabilite_agents = {"news": {"signal": "LONG", "bull_score": 3.0,
                                      "reason": "MACRO_BLOCK"}}

    Orchestrator._log_agents_snapshot_jsonl(
        o, {"technical": {"H1": "LONG"}}, {"news": "LONG"}, {"ATR_H1": 1.5},
        {"price": 100.0}, context="test")

    lignes = (tmp_path / "data" / "agents_snap.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lignes) == 1
    rec = json.loads(lignes[0])
    assert rec["agents_detail"]["news"]["reason"] == "MACRO_BLOCK"
    assert rec["global_signals"] == {"news": "LONG"}      # inchange


def test_snapshot_sans_tracabilite_reste_valide(tmp_path, monkeypatch):
    """Retrocompatibilite : pas de tracabilite -> pas de cle parasite."""
    from orchestrator.orchestrator import Orchestrator

    monkeypatch.chdir(tmp_path)
    o = object.__new__(Orchestrator)
    o.symbol = "XAUUSD"
    o._tracabilite_agents = {}

    Orchestrator._log_agents_snapshot_jsonl(o, {}, {}, {}, {}, context="vide")

    rec = json.loads((tmp_path / "data" / "agents_snap.jsonl").read_text(
        encoding="utf-8").strip())
    assert "agents_detail" not in rec
    assert rec["symbol"] == "XAUUSD"
