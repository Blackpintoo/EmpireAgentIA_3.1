# -*- coding: utf-8 -*-
"""
[RISK_TRACE] : comparer le risque au budget REELLEMENT vise (2026-08-04).

Mesure du 03/08 (5 traces reelles, equite ~98 500 $, risk_per_trade 0,5 %,
max_risk_per_trade_usd 250) :

    symbole   risque engage   ancien ratio   verdict emis
    SP500        250.78 $        0.51x       ERROR « incoherent »
    NAS100       241.62 $        0.49x       ERROR « incoherent »
    SP500        249.39 $        0.51x       ERROR « incoherent »
    SP500        249.30 $        0.51x       ERROR « incoherent »
    BTCUSD       448.31 $        0.91x       aucun

Le budget de reference etait le seul pourcentage du profil (~492 $), alors que
le cap absolu de 250 $ etait plus contraignant et s'appliquait effectivement.
Les indices etaient donc dimensionnes correctement (1,00x du budget effectif)
et denonces a tort, tandis que BTCUSD — seul reellement hors norme a 1,79x —
passait inapercu. Les deux erreurs sont la meme, de signe oppose.
"""
import orchestrator.trade_guards as TG

EQUITE = 98351.0
PCT = 0.005
CAP = 250.0

# (symbole, risque engage, equite au moment de la trace)
TRACES_REELLES = [
    ("SP500", 250.78, 98300.0),
    ("NAS100", 241.62, 98320.0),
    ("SP500", 249.39, 98575.0),
    ("SP500", 249.30, 98588.0),
]


def test_le_cap_absolu_prime_quand_il_est_plus_bas():
    budget, source = TG.budget_risque_effectif(EQUITE, PCT, CAP)
    assert budget == CAP
    assert source == "cap max_risk_per_trade_usd"


def test_le_profil_prime_quand_le_cap_est_plus_haut():
    budget, source = TG.budget_risque_effectif(EQUITE, PCT, 900.0)
    assert abs(budget - EQUITE * PCT) < 1e-9
    assert source == "profil"


def test_les_indices_denonces_a_tort_reviennent_dans_la_fourchette():
    """Les 4 ERROR du 03/08 doivent disparaitre, sans elargir la fourchette."""
    for symbole, risque, equite in TRACES_REELLES:
        budget, _ = TG.budget_risque_effectif(equite, PCT, CAP)
        ratio = risque / budget
        assert 0.75 <= ratio <= 1.25, (
            "%s : ratio %.2fx encore hors fourchette" % (symbole, ratio))
        assert abs(ratio - 1.0) < 0.05, (
            "%s : le cap etant respecte, le ratio doit valoir ~1,00x, pas %.2fx"
            % (symbole, ratio))


def test_btcusd_devient_visible_comme_hors_norme():
    """Le vrai defaut, masque par l'ancien denominateur."""
    budget, source = TG.budget_risque_effectif(98351.0, PCT, CAP)
    ratio = 448.31 / budget
    assert source == "cap max_risk_per_trade_usd"
    assert ratio > 1.25, (
        "BTCUSD engageait 448,31 $ contre un plafond de 250 $ : la trace doit "
        "le signaler, alors qu'elle le donnait a 0,91x")
    assert abs(ratio - 1.79) < 0.01


def test_budget_indisponible_ne_leve_pas():
    assert TG.budget_risque_effectif(None, None, None) == (None, "inconnu")
    budget, source = TG.budget_risque_effectif(None, None, CAP)
    assert budget == CAP and source == "cap max_risk_per_trade_usd"
    budget, source = TG.budget_risque_effectif(EQUITE, PCT, None)
    assert abs(budget - EQUITE * PCT) < 1e-9 and source == "profil"


def test_unite_du_point_val_valeur_d_une_unite_de_prix():
    """
    Temoin de l'erreur d'unite du repli RISK_CAP.

    `risque = distance_en_prix x lots x valeur_unite_de_prix`. Pour SP500
    (contract_size 1.0, point 0.01), l'ancien repli `contract_size x point`
    donnait 0.01 : le risque calcule valait 2,51 $ au lieu de 250,78 $, soit
    100 fois trop peu. Le plafond de 250 $ ne pouvait donc jamais mordre —
    c'est ainsi que BTCUSD a pu engager 448 $.
    """
    contract_size, point = 1.0, 0.01
    distance_prix, lots = 26.123, 9.6

    ancien = distance_prix * lots * (contract_size * point)
    corrige = distance_prix * lots * contract_size

    assert abs(ancien - 2.508) < 0.01
    assert abs(corrige - 250.78) < 0.5
    assert abs(corrige / ancien - 1.0 / point) < 1e-6, "facteur d'erreur = 1/point"
