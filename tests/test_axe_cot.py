# -*- coding: utf-8 -*-
"""
Convention de signe entre le future COT et la paire tradee.

AJOUT 2026-09-13.

Le rapport COT porte sur UNE devise, pas sur une paire. Selon que cette devise
est la BASE ou la COTATION du symbole trade, l'axe coincide ou se retourne.
Rien ne traduisait cet ecart : `contrarian_signal`, calcule sur l'axe du
future, etait compare tel quel a la direction proposee.

Mesure sur guards.log du 10 au 14 aout : sentiment_extreme_against a bloque en
continu les SHORT USDCAD alors que les speculateurs etaient massivement SHORT
CAD — donc alors que la lecture contrarienne soutenait ce meme SHORT USDCAD.

Ces tests fixent le comportement dans les deux sens, et verrouillent la
non-regression sur les symboles deja corrects.
"""
from datetime import datetime, timezone

import pytest

import utils.advanced_sentiment as A

DIRECTES = ["EURUSD", "AUDUSD", "GBPUSD", "XAUUSD", "XAGUSD"]
INVERSEES = ["USDCAD", "USDJPY"]


def _cot(symbole: str, pct_longs: float, chg: int = -6000):
    """COTData avec un ratio speculateurs impose."""
    total = 100000
    nc_long = int(total * pct_longs / 100.0)
    return A.COTData(
        symbol=symbole, report_date=datetime(2026, 9, 9, tzinfo=timezone.utc),
        commercial_long=120000, commercial_short=40000, commercial_net=80000,
        noncommercial_long=nc_long, noncommercial_short=total - nc_long,
        noncommercial_net=nc_long - (total - nc_long),
        open_interest=200000, commercial_net_change=5000,
        noncommercial_net_change=chg,
    )


def analyser(symbole: str, pct_longs: float, chg: int = -6000):
    an = A.AdvancedSentimentAnalyzer(symbol=symbole)
    an._cot_cache = _cot(symbole, pct_longs, chg)
    an._funding_cache = None
    an._is_cache_valid = lambda: True
    return an.analyze()


def garde_bloque(resultat, direction: str) -> bool:
    """Reproduit la condition du garde sentiment_extreme_against."""
    cs = resultat.get("contrarian_signal")
    sc = resultat.get("sentiment_score", 0.0)
    return bool(cs) and cs != direction and abs(sc) > 0.7


# ------------------------------------------------------------ le predicat
@pytest.mark.parametrize("sym", INVERSEES)
def test_axe_inverse_quand_usd_est_la_base(sym):
    assert A.axe_inverse(sym) is True


@pytest.mark.parametrize("sym", DIRECTES)
def test_axe_direct_quand_le_future_suit_la_base(sym):
    assert A.axe_inverse(sym) is False


def test_tout_symbole_du_registre_est_classe():
    """Aucune entree de _SYMBOL_TO_COT_QUERY ne doit rester non traitee."""
    for sym in A._SYMBOL_TO_COT_QUERY:
        assert isinstance(A.axe_inverse(sym), bool)
    # USDCHF est dans le registre sans etre actif : il doit deja etre inverse.
    assert A.axe_inverse("USDCHF") is True


def test_regle_deduite_du_symbole_pas_d_une_table():
    """
    Un symbole ajoute plus tard doit etre traite sans second geste. C'est la
    raison pour laquelle la regle se lit sur le symbole et non dans une table
    parallele qui pourrait deriver.
    """
    assert A.axe_inverse("USDMXN") is True
    assert A.axe_inverse("USDSEK") is True
    assert A.axe_inverse("NZDUSD") is False


@pytest.mark.parametrize("entree", [None, "", 0, [], 12.5])
def test_predicat_ne_leve_jamais(entree):
    assert isinstance(A.axe_inverse(entree), bool)


@pytest.mark.parametrize("valeur,attendu", [
    ("LONG", "SHORT"), ("SHORT", "LONG"), (None, None), ("WAIT", "WAIT"), ("", ""),
])
def test_retournement(valeur, attendu):
    assert A._retourner(valeur) == attendu


# -------------------------------------------- le cas mesure du 10-14 aout
def test_usdcad_speculateurs_short_cad_le_short_passe_desormais():
    """
    8 % de longs CAD : les speculateurs sont massivement SHORT le CAD, donc
    implicitement LONG USDCAD. La lecture contrarienne attend un rebond du CAD,
    soit une BAISSE de USDCAD — elle soutient donc le SHORT USDCAD.

    Avant correction : SHORT USDCAD etait bloque, LONG passait.
    """
    r = analyser("USDCAD", 8.0)
    assert r["axe_traduit"] is True
    assert r["contrarian_signal"] == "SHORT"
    assert garde_bloque(r, "SHORT") is False
    assert garde_bloque(r, "LONG") is True


def test_usdjpy_meme_retournement():
    r = analyser("USDJPY", 8.0)
    assert r["axe_traduit"] is True
    assert r["contrarian_signal"] == "SHORT"
    assert garde_bloque(r, "SHORT") is False
    assert garde_bloque(r, "LONG") is True


def test_cas_symetrique_speculateurs_long_la_devise():
    """
    95 % de longs CAD : contrarien attend une baisse du CAD, donc une HAUSSE
    de USDCAD. Le LONG USDCAD doit passer, le SHORT etre bloque.
    """
    r = analyser("USDCAD", 95.0, chg=+6000)
    assert r["contrarian_signal"] == "LONG"
    assert garde_bloque(r, "LONG") is False
    assert garde_bloque(r, "SHORT") is True


# ------------------------------------------------------- non-regression
@pytest.mark.parametrize("sym", DIRECTES)
def test_symboles_deja_corrects_inchanges(sym):
    """
    Meme etat COT, meme verdict qu'avant le correctif : la devise du future
    est la base, l'axe coincide, rien ne doit bouger.
    """
    r = analyser(sym, 8.0)
    assert r["axe_traduit"] is False
    assert r["contrarian_signal"] == "LONG"
    assert r["sentiment_score"] < 0
    assert garde_bloque(r, "SHORT") is True
    assert garde_bloque(r, "LONG") is False


@pytest.mark.parametrize("sym", DIRECTES + INVERSEES)
def test_score_et_signal_restent_coherents(sym):
    """
    Le score et le signal doivent pointer dans le meme sens apres traduction,
    sinon la note de decision `sentiment:LONG(-0.72)` devient illisible.
    """
    for pct in (8.0, 95.0):
        r = analyser(sym, pct, chg=(-6000 if pct < 50 else 6000))
        if r["signal"] == "LONG":
            assert r["sentiment_score"] > 0, (sym, pct, r["sentiment_score"])
        elif r["signal"] == "SHORT":
            assert r["sentiment_score"] < 0, (sym, pct, r["sentiment_score"])


@pytest.mark.parametrize("sym", DIRECTES + INVERSEES)
def test_amplitude_du_score_inchangee(sym):
    """
    Le correctif touche au SIGNE, pas a l'amplitude. La renormalisation du
    score sur le forex sans funding est une question distincte, laissee
    ouverte : ce test tombera si quelqu'un la traite ici par inadvertance.
    """
    r = analyser(sym, 8.0)
    assert abs(abs(r["sentiment_score"]) - 0.72) < 1e-9


def test_contrarian_absent_hors_extreme():
    """Entre les deux seuils, aucun signal contrarien, donc aucun blocage."""
    for sym in ("USDCAD", "EURUSD"):
        r = analyser(sym, 50.0, chg=0)
        assert r["contrarian_signal"] is None
        assert garde_bloque(r, "LONG") is False
        assert garde_bloque(r, "SHORT") is False


def test_symbole_sans_cot_ne_leve_pas():
    """NAS100 n'est pas dans le registre COT : pas de donnee, pas de blocage."""
    an = A.AdvancedSentimentAnalyzer(symbol="NAS100")
    an._cot_cache = None
    an._funding_cache = None
    an._is_cache_valid = lambda: True
    r = an.analyze()
    assert r["contrarian_signal"] is None
    assert r["axe_traduit"] is False
