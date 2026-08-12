# -*- coding: utf-8 -*-
"""
trade_mfe.csv : interroger MT5 par position, pas par fenetre (2026-08-12).

Mesure sur 7 jours de production (04/08 20:58 -> 12/08), compte 25832276 :

    clotures reelles                                  33
    lignes ecrites                                    33
    lignes resolues                                    0
    « aucun deal trouve apres 15 cycles »             44

Le filtre sur les deals de SORTIE etait correct — verifie sur 6 clotures
rejouees depuis data/deals_history.csv. Ce qui manquait, c'etait la MATIERE :
`history_deals_get(debut, fin)` ne ramenait pas les deals de sortie. La
requete par `position=` interroge l'historique du compte par identifiant, sans
fenetre temporelle.
"""
from types import SimpleNamespace

import utils.position_manager as PM


class FauxDeal:
    def __init__(self, position_id, entry, price, profit=0.0, time_=0,
                 order=0, commission=0.0, swap=0.0):
        self.position_id = position_id
        self.entry = entry
        self.price = price
        self.profit = profit
        self.time = time_
        self.order = order or position_id
        self.commission = commission
        self.swap = swap


class FauxMT5:
    """MT5 minimal : ne repond QUE par position, jamais par fenetre."""

    def __init__(self, par_position):
        self._par_position = par_position
        self.appels = []

    def history_deals_get(self, *args, **kwargs):
        if "position" in kwargs:
            self.appels.append(("position", kwargs["position"]))
            return tuple(self._par_position.get(int(kwargs["position"]), ()))
        self.appels.append(("fenetre", args))
        return ()          # exactement le comportement observe en production


def test_la_requete_par_position_resout_ce_que_la_fenetre_manquait(monkeypatch):
    ticket = 1698148556
    faux = FauxMT5({ticket: [
        FauxDeal(ticket, entry=0, price=7584.71, profit=0.0, time_=100),
        FauxDeal(ticket, entry=1, price=7601.30, profit=159.28, time_=900),
    ]})
    monkeypatch.setattr(PM, "mt5", faux)

    # `deals_fenetre` vide : c'est la situation de production.
    pnl, prix, sorties, origine = PM._pnl_et_prix_sortie_par_ticket(ticket, [])

    assert origine == "position_id"
    assert sorties and prix == 7601.30 and pnl == 159.28


def test_repli_sur_la_fenetre_si_la_requete_directe_est_muette(monkeypatch):
    """Une version de terminal sans `position=` ne doit pas faire pire qu'avant."""
    ticket = 42

    class MT5Muet:
        def history_deals_get(self, *a, **k):
            raise TypeError("position non supporte")

    monkeypatch.setattr(PM, "mt5", MT5Muet())

    fenetre = [
        FauxDeal(ticket, entry=0, price=100.0, profit=0.0, time_=1),
        FauxDeal(ticket, entry=1, price=105.0, profit=50.0, time_=2),
    ]
    pnl, prix, sorties, origine = PM._pnl_et_prix_sortie_par_ticket(ticket, fenetre)

    assert origine == "fenetre"
    assert prix == 105.0 and pnl == 50.0


def test_aucune_source_ne_ment_sur_l_absence(monkeypatch):
    monkeypatch.setattr(PM, "mt5", FauxMT5({}))
    pnl, prix, sorties, origine = PM._pnl_et_prix_sortie_par_ticket(999, [])
    assert origine == "aucun"
    assert sorties == [] and pnl is None and prix is None


def test_le_deal_d_entree_seul_ne_resout_toujours_pas(monkeypatch):
    """La requete directe ne doit pas reintroduire le defaut du 02/08."""
    ticket = 77
    faux = FauxMT5({ticket: [FauxDeal(ticket, entry=0, price=100.0, time_=1)]})
    monkeypatch.setattr(PM, "mt5", faux)

    pnl, prix, sorties, origine = PM._pnl_et_prix_sortie_par_ticket(ticket, [])
    assert sorties == [] and pnl is None and prix is None


def test_mt5_absent_ne_leve_pas(monkeypatch):
    monkeypatch.setattr(PM, "mt5", None)
    assert PM._deals_du_ticket(1) is None
    pnl, prix, sorties, origine = PM._pnl_et_prix_sortie_par_ticket(1, [])
    assert origine == "aucun"


def test_la_fenetre_d_attente_couvre_plus_de_cinq_minutes():
    """15 cycles (~5 min) abandonnaient 44 fois en 7 jours."""
    assert PM._MFE_ATTENTE_MAX_CYCLES >= 60
