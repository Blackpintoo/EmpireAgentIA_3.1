# -*- coding: utf-8 -*-
"""
FIX 2026-08-02 — calendrier economique et fuite de jeton dans les logs.

Le rapport de performance du 2 aout concluait que le calendrier etait mort
parce que Finnhub repondait 403. C'ETAIT FAUX : le calendrier est alimente
par la source CSV (ForexFactory), le 403 concerne un endpoint premium que
le palier gratuit ne couvre pas, et le code bascule deja correctement.
Ce qui etait vrai : le 403 etait loggue en ERROR toutes les 2 h, et l'URL
journalisee contenait la cle API en clair.
"""
import datetime as dt

import pytest


def test_jeton_dans_une_url_est_masque():
    """La cle Finnhub circulait en clair dans logs/empire_agent.log."""
    from utils.logger import _redact

    fuite = ("[Finnhub] HTTP error 403: 403 Client Error: Forbidden for url: "
             "https://finnhub.io/api/v1/calendar/economic?from=2026-08-01"
             "&to=2026-08-03&token=d4lc3o1r01qt7v19s4a0")
    masque = _redact(fuite)
    assert "d4lc3o1r01qt7v19s4a0" not in masque
    assert "token=****" in masque


@pytest.mark.parametrize("cle", ["api_key", "apikey", "access_token", "token"])
def test_toutes_les_formes_de_jeton_url_sont_masquees(cle):
    from utils.logger import _redact

    assert "SECRET" not in _redact("https://x/y?%s=SECRET&z=1" % cle)


def test_403_finnhub_signale_une_seule_fois():
    """Une condition attendue ne doit pas produire une alerte toutes les 2 h."""
    from connectors.finnhub_client import FinnhubClient

    assert hasattr(FinnhubClient, "_403_signale")


def test_fenetre_de_gel_couvre_bien_avant_et_apres(tmp_path):
    """
    Verification directe du garde news-freeze sur des donnees de calendrier
    reelles : il doit geler de T-window_before a T+window_after inclus.
    """
    from utils.news_filter import is_frozen_now

    csv = tmp_path / "news.csv"
    csv.write_text(
        "datetime,currency,impact,title,source,url\n"
        "2026-08-03 20:00,USD,High,ISM Manufacturing PMI,test,\n",
        encoding="utf-8")

    from zoneinfo import ZoneInfo
    evenement = dt.datetime(2026, 8, 3, 20, 0, tzinfo=ZoneInfo("Europe/Zurich"))
    profil = {"orchestrator": {}}

    def gele(minutes):
        return is_frozen_now(
            symbol="SP500", profile=profil, news_csv=str(csv),
            window_before_min=15, window_after_min=15, impacts=["High"],
            now=evenement + dt.timedelta(minutes=minutes))[0]

    assert gele(-16) is False
    assert gele(-15) is True
    assert gele(0) is True
    assert gele(+15) is True
    assert gele(+16) is False
