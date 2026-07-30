# -*- coding: utf-8 -*-
"""P5 : cloisonnement des donnees de performance par compte MT5."""
import importlib

import pytest

import utils.account_scope as SCOPE


@pytest.fixture(autouse=True)
def _cache_propre():
    SCOPE.reinitialiser_cache()
    yield
    SCOPE.reinitialiser_cache()


def test_numero_compte_depuis_env(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "25832276")
    assert SCOPE.numero_compte() == "25832276"


def test_numero_compte_assainit_les_caracteres_dangereux(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "../../etc/passwd")
    assert "/" not in SCOPE.numero_compte()
    assert ".." not in SCOPE.numero_compte()


def test_compte_absent_ne_se_melange_pas_a_un_compte_connu(monkeypatch):
    monkeypatch.delenv("MT5_ACCOUNT", raising=False)
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.setattr(SCOPE, "_depuis_config", lambda: None)
    assert SCOPE.numero_compte() == "inconnu"
    assert "compte_inconnu" in str(SCOPE.chemin_donnees("x.csv"))


def test_chemins_cloisonnes(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "111")
    assert str(SCOPE.chemin_donnees("trade_outcomes.csv")).replace("\\", "/") \
        == "data/compte_111/trade_outcomes.csv"
    assert str(SCOPE.chemin_scope("data/performance/tracker_BTCUSD.json")).replace("\\", "/") \
        == "data/performance/compte_111/tracker_BTCUSD.json"


def test_deux_comptes_ne_partagent_aucun_chemin(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "111")
    SCOPE.reinitialiser_cache()
    a = SCOPE.chemin_donnees("trade_outcomes.csv")
    monkeypatch.setenv("MT5_ACCOUNT", "222")
    SCOPE.reinitialiser_cache()
    b = SCOPE.chemin_donnees("trade_outcomes.csv")
    assert a != b


def test_tracker_de_performance_est_cloisonne(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "999")
    SCOPE.reinitialiser_cache()
    import utils.performance_tracker as PT
    importlib.reload(PT)
    chemin = str(PT._symbol_tracker_path("BTCUSD")).replace("\\", "/")
    assert chemin == "data/performance/compte_999/tracker_BTCUSD.json"


def test_outcome_tracker_est_cloisonne(monkeypatch):
    monkeypatch.setenv("MT5_ACCOUNT", "888")
    SCOPE.reinitialiser_cache()
    from utils.trade_outcome_tracker import OutcomeTrackerConfig
    assert "compte_888" in OutcomeTrackerConfig().history_file
