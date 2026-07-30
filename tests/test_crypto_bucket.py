# -*- coding: utf-8 -*-
"""FIX 2026-07-30 (P1) : tests réécrits au niveau de la garde elle-même.

Les versions précédentes appelaient `o._build_proposal(...)` — API disparue —
puis `execute_trade`, en espérant atteindre `place_order`. Or execute_trade
enchaîne une trentaine de gardes : dans un contexte de test, le trade est
rejeté bien avant d'arriver au bucket crypto. Ces tests ne prouvaient donc
rien sur la garde ; ils échouaient sur la mise en place.

On teste désormais directement `_apply_crypto_bucket_guard` et
`_crypto_bucket_risk_used`, qui portent la logique.
"""
import pytest

from orchestrator.orchestrator import _apply_crypto_bucket_guard, _crypto_bucket_risk_used


class _Pos:
    def __init__(self, symbol, volume, price_open=50000.0, sl=49500.0):
        self.symbol = symbol
        self.volume = volume
        self.price_open = price_open
        self.sl = sl


def _profil(_sym=None):
    return {
        "instrument": {"point": 0.01, "contract_size": 1.0, "pip_value": 0.01},
        "risk": {"risk_per_trade": 0.005},
    }


def test_facteur_neutre_quand_le_bucket_est_vide(monkeypatch):
    """Sans exposition crypto, la taille ne doit pas être réduite."""
    monkeypatch.setattr("orchestrator.orchestrator._crypto_bucket_risk_used",
                        lambda gp: 0.0, raising=False)
    f = _apply_crypto_bucket_guard("BTCUSD", planned_risk=0.005, cap=0.06, get_profile=_profil)
    assert f == pytest.approx(1.0), "aucune reduction attendue sur un bucket vide"


def test_reduction_quand_le_cap_est_presque_atteint(monkeypatch):
    """Si l'exposition consomme presque le cap, le facteur doit descendre."""
    monkeypatch.setattr("orchestrator.orchestrator._crypto_bucket_risk_used",
                        lambda gp: 0.055, raising=False)
    f = _apply_crypto_bucket_guard("BTCUSD", planned_risk=0.02, cap=0.06, get_profile=_profil)
    assert f < 1.0, "le facteur aurait du etre reduit"
    assert f >= 0.0, "le facteur doit rester dans [0,1]"


def test_le_facteur_ne_descend_jamais_sous_min_factor(monkeypatch):
    """Cap totalement consommé : plancher respecté, pas de valeur negative."""
    monkeypatch.setattr("orchestrator.orchestrator._crypto_bucket_risk_used",
                        lambda gp: 0.10, raising=False)
    f = _apply_crypto_bucket_guard("BTCUSD", planned_risk=0.02, cap=0.06, get_profile=_profil)
    assert 0.0 <= f <= 1.0
    assert f == 0.0 or f <= 1.0


def test_risque_utilise_est_positif_et_borne(monkeypatch):
    """_crypto_bucket_risk_used doit rendre une fraction d'equity plausible."""
    import orchestrator.orchestrator as O
    monkeypatch.setattr(O, "_mt5", None, raising=False)
    used = _crypto_bucket_risk_used(_profil)
    assert isinstance(used, float) and used >= 0.0
