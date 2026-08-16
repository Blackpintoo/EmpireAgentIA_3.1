# -*- coding: utf-8 -*-
"""
Tests du court-circuit de SentimentAgent sur les symboles non crypto.

AJOUT 2026-08-16.

Le point delicat n'est pas le predicat — c'est de prouver que court-circuiter
ne change RIEN au vote. La preuve tient a un fait verifiable : l'agent lui-meme
refuse deja tout symbole non crypto. Si ce fait cesse d'etre vrai, le test
`test_agent_refuse_bien_les_non_crypto` tombe, et le court-circuit doit etre
revu. C'est exactement le garde-fou qu'on veut.
"""
import pytest
import yaml

from utils.pertinence_sentiment import sentiment_pertinent

CRYPTO = ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "LTCUSD", "DOGEUSD"]
NON_CRYPTO = ["NAS100", "SP500", "AUDUSD", "USDJPY", "XAUUSD", "DJ30",
              "UK100", "GBPUSD", "USDCAD", "GER40", "XAGUSD", "EURUSD"]


@pytest.mark.parametrize("sym", CRYPTO)
def test_crypto_reste_pertinent(sym):
    pertinent, motif = sentiment_pertinent(sym)
    assert pertinent is True
    assert motif == "symbole crypto"


@pytest.mark.parametrize("sym", NON_CRYPTO)
def test_non_crypto_court_circuite(sym):
    pertinent, motif = sentiment_pertinent(sym)
    assert pertinent is False
    assert motif == "non_crypto"


@pytest.mark.parametrize("sym", NON_CRYPTO)
def test_agent_refuse_bien_les_non_crypto(sym):
    """
    LE test qui justifie le court-circuit.

    On n'ecourte un appel que parce que son resultat est connu d'avance. Si
    SentimentAgent se met un jour a produire un signal hors crypto, ce test
    echoue avant que le court-circuit ne fasse disparaitre un vrai vote.

    Aucun reseau : la garde non_crypto retourne avant tout appel HTTP.
    """
    from agents.sentiment import SentimentAgent

    out = SentimentAgent(symbol=sym).generate_signal()
    assert isinstance(out, dict)
    assert out.get("signal") is None
    assert out.get("reason") == "non_crypto"


def test_derogation_de_profil_force_l_appel():
    """Le jour ou l'agent aura de vraies sources hors crypto, une cle suffit."""
    cfg = {"sentiment": {"enabled": True, "non_crypto": True}}
    pertinent, motif = sentiment_pertinent("XAUUSD", cfg)
    assert pertinent is True
    assert "derogation" in motif


def test_enabled_true_ne_vaut_pas_derogation():
    """
    Piege a eviter : `sentiment: {enabled: true}` est DEJA pose sur XAUUSD,
    EURUSD, USDJPY et USOUSD. S'en servir comme derogation annulerait le
    correctif sur ces symboles.
    """
    cfg = {"sentiment": {"enabled": True}}
    pertinent, _ = sentiment_pertinent("XAUUSD", cfg)
    assert pertinent is False


@pytest.mark.parametrize("cfg", [
    None, {}, {"sentiment": None}, {"sentiment": "pas un dict"},
    {"sentiment": {"non_crypto": "oui"}}, {"sentiment": {"non_crypto": 1}},
])
def test_configurations_bancales_ne_derogent_pas(cfg):
    """Seul `non_crypto: true` (booleen) deroge. Pas 1, pas 'oui'."""
    pertinent, _ = sentiment_pertinent("NAS100", cfg)
    assert pertinent is False


def test_symbole_absurde_ne_leve_pas():
    for sym in (None, "", 0, [], "???"):
        pertinent, motif = sentiment_pertinent(sym)
        assert isinstance(pertinent, bool)
        assert isinstance(motif, str)


def test_ouverture_en_cas_de_doute(monkeypatch):
    """
    Si le predicat devient introuvable, on laisse passer : le comportement
    d'avant le correctif est preserve. Un garde d'observabilite ne doit
    jamais pouvoir supprimer un vote par accident.
    """
    import builtins
    vrai_import = builtins.__import__

    def faux_import(nom, *a, **k):
        if nom == "agents.sentiment":
            raise ImportError("simulation")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", faux_import)
    pertinent, motif = sentiment_pertinent("NAS100")
    assert pertinent is True
    assert "indisponible" in motif


def test_couverture_des_symboles_reellement_actifs():
    """
    Recense l'effet reel sur les symboles actifs du depot, pour que le compte
    annonce dans le rapport soit verifiable et ne derive pas en silence.
    """
    d = yaml.safe_load(open("config/profiles.yaml", encoding="utf-8"))
    actifs = d["enabled_symbols"]
    profils = d.get("profiles") or {}

    court_circuites = [s for s in actifs
                       if not sentiment_pertinent(s, (profils.get(s) or {}).get("agents"))[0]]
    conserves = [s for s in actifs if s not in court_circuites]

    assert conserves == ["BTCUSD"], (
        "seul BTCUSD devait conserver un vote sentiment, obtenu : %s" % conserves)
    assert len(court_circuites) == len(actifs) - 1
