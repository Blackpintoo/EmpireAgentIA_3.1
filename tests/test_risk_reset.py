# -*- coding: utf-8 -*-
"""FIX 2026-07-30 (P1) : test réécrit sur l'API réelle.

L'ancienne version appelait `rm._today_loss_pct()`, méthode qui n'existe plus :
RiskManager ne calcule plus lui-même la perte du jour, elle lui est passée en
paramètre par l'orchestrateur. Le test échouait donc sur une AttributeError et
ne vérifiait plus rien depuis la refonte.
"""
import pytest


def _rm():
    from utils.risk_manager import RiskManager
    rm = RiskManager(symbol="BTCUSD")
    rm.get_equity = lambda: 10000.0
    return rm


def test_limite_journaliere_non_atteinte_a_zero():
    rm = _rm()
    assert rm.is_daily_limit_reached(daily_loss_pct=0.0, consec_losses=0) is False


def test_limite_journaliere_atteinte_par_perte():
    rm = _rm()
    seuil = abs(rm.daily_loss_limit_pct)
    assert rm.is_daily_limit_reached(daily_loss_pct=-(seuil + 0.001)) is True
    assert rm.is_daily_limit_reached(daily_loss_pct=-(seuil / 2)) is False


def test_limite_journaliere_atteinte_par_serie_de_pertes():
    rm = _rm()
    n = int(rm.max_consecutive_losses)
    assert rm.is_daily_limit_reached(daily_loss_pct=0.0, consec_losses=n) is True
    assert rm.is_daily_limit_reached(daily_loss_pct=0.0, consec_losses=n - 1) is False


def test_reset_journalier_remet_l_echelle_de_risque_a_un():
    rm = _rm()
    rm._risk_scale_today = 0.5
    rm._last_reset_day = "1970-01-01"
    rm._maybe_reset_day()
    assert rm._risk_scale_today == 1.0
