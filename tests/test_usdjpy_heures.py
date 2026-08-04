# -*- coding: utf-8 -*-
"""
USDJPY : la whitelist locale doit primer sur la blacklist globale (2026-08-04).

Temoin du defaut mesure en production le 03/08. La blacklist GLOBALE
[3,4,7,10,11,12,13,14] et la whitelist locale allowed_hours_utc [8..15]
s'additionnaient en union : il ne restait que les heures 8, 9 et 15 ouvertes.
Sur 632 decisions USDJPY dans la journee, 67 signaux atteignaient le seuil de
proposition (score >= 7.0) dans une heure fermee, contre 2 dans une heure
ouverte. Aucun trade n'a ete execute.

Ces tests verifient le mecanisme ET la configuration reelle : editer
overrides.yaml sans y penser doit faire echouer la suite.
"""
import orchestrator.orchestrator as ORCH
import orchestrator.trade_guards as TG

# Ce que la mesure du 03/08 a montre : ces heures portaient les signaux de
# qualite et etaient fermees par la seule blacklist globale.
HEURES_A_ROUVRIR = [10, 11, 12, 13, 14]
# Hors whitelist London+NY : elles doivent RESTER fermees.
HEURES_TOUJOURS_FERMEES = [3, 4, 7]


def _config_reelle():
    """(blacklist globale, whitelist locale USDJPY) lues dans overrides.yaml."""
    from utils.config import get_overrides
    ov = get_overrides() or {}
    globale = list(
        ((ov.get("GLOBAL") or {}).get("orchestrator") or {}).get("blocked_hours_utc", []) or [])
    locale = list(
        ((ov.get("USDJPY") or {}).get("orchestrator") or {}).get("allowed_hours_utc", []) or [])
    return globale, locale


def test_usdjpy_peut_soustraire_sa_whitelist():
    assert "USDJPY" in ORCH.BLACKLIST_OVERRIDE_WHITELIST


def test_les_heures_porteuses_de_signal_sont_rouvertes():
    globale, locale = _config_reelle()
    assert globale, "blacklist globale introuvable dans overrides.yaml"
    assert locale, "allowed_hours_utc USDJPY introuvable dans overrides.yaml"

    bloquees, _ = TG.calculer_blocked_hours(
        "USDJPY", [], globale, locale, ORCH.BLACKLIST_OVERRIDE_WHITELIST, 12)

    for h in HEURES_A_ROUVRIR:
        assert h not in bloquees, "heure %d encore bloquee : les %s signaux du 03/08 restent perdus" % (
            h, "20" if h == 12 else "")


def test_la_blacklist_reste_appliquee_hors_de_la_fenetre():
    """Le contournement ne doit pas devenir une levee pure et simple."""
    globale, locale = _config_reelle()
    bloquees, _ = TG.calculer_blocked_hours(
        "USDJPY", [], globale, locale, ORCH.BLACKLIST_OVERRIDE_WHITELIST, 3)

    for h in HEURES_TOUJOURS_FERMEES:
        assert h in bloquees, "heure %d devrait rester bloquee (hors London+NY)" % h


def test_temoin_du_defaut_sans_le_contournement():
    """Sans l'inscription, l'union refermait les heures porteuses."""
    globale, locale = _config_reelle()
    bloquees, _ = TG.calculer_blocked_hours(
        "USDJPY", [], globale, locale, ["XAUUSD"], 12)

    assert 12 in bloquees and 13 in bloquees and 14 in bloquees


def test_les_autres_symboles_ne_sont_pas_affectes():
    """GBPUSD n'est pas inscrit : l'union stricte continue de s'appliquer."""
    bloquees, _ = TG.calculer_blocked_hours(
        "GBPUSD", [], [3, 4, 12], [8, 9, 10, 11, 12], ORCH.BLACKLIST_OVERRIDE_WHITELIST, 12)

    assert bloquees == [3, 4, 12]
