# -*- coding: utf-8 -*-
"""
Plafond de volume exprime en argent, pas en lots (2026-08-12).

Defaut mesure en production sur BTCUSD, 5 ordres du 05/08 au 08/08 plus un
du 03/08 :

    distance de stop   lots   risque engage   ratio / budget 250 $
      49 264 pts       0.91      448.31 $          1.79x
      16 912 pts       0.91      153.90 $          0.62x
       6 585 pts       0.91       59.92 $          0.24x
       5 686 pts       0.91       51.75 $          0.21x

Lots constants, risque variant d'un facteur 9 : le plafond `max_volume: 0.91`
ramenait les 7,6 lots demandes par le budget sans que le risque resultant ne
soit recalcule. Un plafond en LOTS ne dit rien tant qu'on ignore la distance
de stop.
"""
import pytest

import utils.risk_manager as RM

BUDGET = 250.0
VALEUR_POINT = 0.01          # BTCUSD : contract_size 1.0 x point 0.01
BANDE = (0.75, 1.25)

# Les distances reellement observees, plus un balayage large.
DISTANCES_OBSERVEES = [49264.4, 16911.9, 6584.6, 6510.0, 5686.4]
DISTANCES_BALAYAGE = [4000, 5000, 7500, 10000, 15000, 25000, 40000, 60000, 90000]


def _profil_btcusd(dynamique=True, absolu=5.0):
    return {
        "instrument": {"point": 0.01, "min_lot": 0.01, "lot_step": 0.01,
                       "contract_size": 1.0, "pip_value": 0.01},
        "risk": {"risk_per_trade": 0.005},
        "orchestrator": {"position_limits": {
            "max_volume": 0.91,
            "max_volume_dynamique": dynamique,
            "max_volume_absolu": absolu,
        }},
    }


def _cfg():
    return {"risk": {"max_risk_per_trade_usd": BUDGET},
            "broker_costs": {"spread_points": 0.0, "slippage_points_entry": 0.0,
                             "slippage_points_exit": 0.0}}


def _ratio(lots, distance):
    return (lots * distance * VALEUR_POINT) / BUDGET


# ---------------------------------------------------------------- fonction pure

def test_le_plafond_statique_reste_le_defaut():
    """Un symbole qui n'a pas demande le mode monetaire ne bouge pas."""
    plafond, source = RM.plafond_volume_effectif(
        BUDGET, 6510.0, VALEUR_POINT, max_volume=0.91, dynamique=False)
    assert plafond == 0.91
    assert source == "max_volume"


def test_le_plafond_monetaire_suit_la_distance_de_stop():
    serre, _ = RM.plafond_volume_effectif(
        BUDGET, 5686.4, VALEUR_POINT, 0.91, 5.0, dynamique=True)
    large, _ = RM.plafond_volume_effectif(
        BUDGET, 49264.4, VALEUR_POINT, 0.91, 5.0, dynamique=True)
    assert serre > large, "le plafond doit s'elargir quand le stop se resserre"
    assert abs(large - BUDGET / (49264.4 * VALEUR_POINT)) < 1e-9


def test_le_garde_absolu_borne_les_stops_tres_serres():
    plafond, source = RM.plafond_volume_effectif(
        BUDGET, 500.0, VALEUR_POINT, 0.91, 5.0, dynamique=True)
    assert plafond == 5.0
    assert source == "max_volume_absolu"


def test_budget_indisponible_retombe_sur_le_plafond_statique():
    plafond, source = RM.plafond_volume_effectif(
        None, 6510.0, VALEUR_POINT, 0.91, 5.0, dynamique=True)
    assert plafond == 0.91
    assert "max_volume" in source


# ------------------------------------------------------- dimensionnement reel

@pytest.mark.parametrize("distance", DISTANCES_OBSERVEES + DISTANCES_BALAYAGE)
def test_le_ratio_reste_dans_la_fourchette_apres_correction(distance):
    rm = RM.RiskManager("BTCUSD", profile=_profil_btcusd(), cfg=_cfg())
    lots = rm.compute_position_size(equity=99547.0, stop_distance_points=distance)

    assert lots is not None, "distance %g : trade refuse alors qu'il est finançable" % distance
    ratio = _ratio(lots, distance)
    assert BANDE[0] <= ratio <= BANDE[1], (
        "distance %g pts : %.2f lot(s) -> ratio %.2fx, hors [0,75 ; 1,25]"
        % (distance, lots, ratio))


# Au-dela de cette distance, 250 $ de budget tiennent dans 0,91 lot : le
# plafond statique ne mord plus. 250 / (0,91 x 0,01) = 27 472 points.
SEUIL_OU_LE_PLAFOND_STATIQUE_MORD = 27472.0


@pytest.mark.parametrize("distance", DISTANCES_OBSERVEES)
def test_temoin_le_plafond_statique_sous_dimensionne_les_stops_serres(distance):
    """
    Avec le plafond statique, tout stop plus serre que ~27 500 points est
    ecrete a 0,91 lot et sort de la fourchette par le bas. C'est le cas de
    4 des 5 ordres mesures.

    Note : le 1,79x du 03/08 demandait EN PLUS l'ancien budget de ~498 $, que
    le present correctif ramene a 250 $. Les deux etages se cumulaient.
    """
    rm = RM.RiskManager("BTCUSD", profile=_profil_btcusd(dynamique=False),
                        cfg=_cfg())
    lots = rm.compute_position_size(equity=99547.0, stop_distance_points=distance)
    assert lots is not None
    ratio = _ratio(lots, distance)

    if distance < SEUIL_OU_LE_PLAFOND_STATIQUE_MORD:
        assert abs(lots - 0.91) < 1e-9, "le plafond statique doit ecreter a 0,91"
        assert ratio < BANDE[0], (
            "distance %g : ecrete a 0,91 lot, le ratio devrait tomber sous 0,75"
            % distance)
    else:
        assert lots < 0.91, "au-dela du seuil, le plafond ne mord plus"
        assert BANDE[0] <= ratio <= BANDE[1]


def test_l_exposition_ne_varie_plus_d_un_facteur_neuf():
    """Le symptome d'origine : meme lot, risque variant d'un facteur 9."""
    rm = RM.RiskManager("BTCUSD", profile=_profil_btcusd(), cfg=_cfg())
    risques = []
    for d in DISTANCES_OBSERVEES:
        lots = rm.compute_position_size(equity=99547.0, stop_distance_points=d)
        risques.append(lots * d * VALEUR_POINT)

    assert max(risques) / min(risques) < 1.7, (
        "dispersion du risque encore trop large : %s" % [round(r, 2) for r in risques])


def test_refus_quand_le_lot_minimum_depasse_le_budget_de_plus_de_25_pct():
    """
    Stop si large que 0,01 lot — le minimum — engage plus de 1,25x le budget.
    Auparavant `max(min_lot, lots)` reintroduisait ce risque en silence.
    """
    rm = RM.RiskManager("BTCUSD", profile=_profil_btcusd(), cfg=_cfg())
    # 0.01 lot x 4 000 000 pts x 0.01 = 400 $ > 1,25 x 250 $
    lots = rm.compute_position_size(equity=99547.0, stop_distance_points=4_000_000)
    assert lots is None


def test_les_autres_symboles_gardent_leur_dimensionnement():
    """Non-regression : sans la cle, le comportement est celui d'avant."""
    profil = {
        "instrument": {"point": 0.01, "min_lot": 0.01, "lot_step": 0.01,
                       "contract_size": 1.0, "pip_value": 0.01},
        "risk": {"risk_per_trade": 0.005},
        "orchestrator": {"position_limits": {"max_volume": 26.0}},
    }
    rm = RM.RiskManager("SP500", profile=profil, cfg=_cfg())
    lots = rm.compute_position_size(equity=99547.0, stop_distance_points=2612.3)
    assert lots is not None
    ratio = (lots * 2612.3 * 0.01) / BUDGET
    assert BANDE[0] <= ratio <= BANDE[1]
