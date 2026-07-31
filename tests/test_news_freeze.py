import pathlib, csv, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from datetime import timedelta

THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.news_filter import is_frozen_now, TZ

def test_freeze_from_csv(tmp_path):
    # CSV temporaire avec une news High USD à maintenant
    csv_path = tmp_path / "news.csv"
    now = datetime.now(TZ)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime","currency","impact","title"])
        w.writerow([now.strftime("%Y-%m-%d %H:%M"), "USD", "High", "Test Event"])

    profile = {"instrument": {"currencies": ["USD"]}}
    frozen, why = is_frozen_now(
        symbol="BTCUSD", profile=profile,
        news_csv=str(csv_path),
        window_before_min=10, window_after_min=10,
        impacts=["High"],
        now=now
    )
    assert frozen and "USD/High" in why


def test_manual_freeze_window():
    profile = {"instrument": {"currencies": ["USD"]}}
    now = datetime.now(TZ)
    s_dt = (now - timedelta(minutes=1)).replace(microsecond=0)
    e_dt = (now + timedelta(minutes=1)).replace(microsecond=0)
    frozen, why = is_frozen_now(
        symbol="BTCUSD", profile=profile,
        manual_freezes=[(s_dt.isoformat(), e_dt.isoformat())],
        now=now
    )
    assert frozen and "manual_freeze" in why


# ══════════════════════════════════════════════════════════════════════════
# FIX 2026-07-31 — tri pertinence / bruit du registre de sources.
# Constate sur la machine de production via tools/test_news_sources.py.
# ══════════════════════════════════════════════════════════════════════════

def test_mot_ambigu_seul_ne_rend_pas_pertinent():
    """
    « Jersey Mike's spent almost "zero dollars" on digital » obtenait 0,70
    de pertinence pour XAUUSD, AUDUSD ET BTCUSD sur la seule presence du
    mot « dollars », et pesait plus lourd que la moitie des depeches de
    banque centrale.
    """
    from utils.news_sources import relevance, keywords_for

    item = {"title": "Jersey Mike's spent almost 'zero dollars' on digital",
            "summary": "The sandwich chain says its digital strategy cost almost nothing.",
            "tier": 2}
    for sym in ("XAUUSD", "AUDUSD", "BTCUSD"):
        assert relevance(item, keywords_for(sym)) == 0.0, sym


def test_appariement_sur_les_limites_de_mot():
    """« aud » se trouvait dans « fraud », « boe » dans « boeing »."""
    from utils.news_sources import relevance, keywords_for

    item = {"title": "Fraud charges filed against a Boeing supplier",
            "summary": "No market relevance.", "tier": 2}
    assert relevance(item, keywords_for("AUDUSD")) == 0.0


def test_un_mot_cle_franc_conserve_son_score():
    """Le correctif ne doit RIEN changer aux articles reellement pertinents."""
    from utils.news_sources import relevance, keywords_for

    item = {"title": "Australian Dollar sticks to intraday gains",
            "summary": "AUD/USD holds firm as the RBA stays put.", "tier": 2}
    assert relevance(item, keywords_for("AUDUSD")) == 1.0


def test_crypto_reste_un_mot_cle_franc():
    """
    Les flux de tier 3 sont exclusivement crypto : y traiter « crypto »
    comme ambigu reviendrait a jeter leur contenu.
    """
    from utils.news_sources import _MOTS_AMBIGUS

    assert "crypto" not in _MOTS_AMBIGUS
    assert "digital asset" not in _MOTS_AMBIGUS


def test_flux_mort_retire_du_registre():
    """treasury : 0 article mesure en production le 31/07/2026."""
    from utils.news_sources import SOURCES

    assert "treasury" not in {f["id"] for f in SOURCES}
