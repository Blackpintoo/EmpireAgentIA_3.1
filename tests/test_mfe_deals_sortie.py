# -*- coding: utf-8 -*-
"""
trade_mfe.csv : seuls les deals de SORTIE resolvent une cloture (2026-08-04).

Temoin du defaut mesure en production : entre le 02/08 22:16 et le 04/08, les
5 lignes ecrites portaient toutes pnl=0.0 et exit==entry, tout en etant
marquees resolu=True. Le deal d'ENTREE, publie des l'ouverture et portant le
meme numero que la position, suffisait a satisfaire la condition d'ecriture.
"""
import utils.position_manager as PM


class FauxDeal:
    """Deal MT5 minimal. `entry` : 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY."""

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


def test_le_deal_d_entree_seul_ne_resout_pas_la_cloture():
    # Exactement la situation de production : seule l'ouverture est publiee.
    deals = [FauxDeal(position_id=1698148556, entry=0, price=7584.71,
                      profit=0.0, time_=100)]
    pnl, prix, sorties = PM._pnl_et_prix_sortie(deals, 1698148556)
    assert sorties == []
    assert pnl is None and prix is None, (
        "un deal d'entree ne doit jamais valoir resolution : c'est ce qui "
        "produisait pnl=0.0 et exit==entry")


def test_le_deal_de_sortie_donne_le_vrai_pnl_et_le_vrai_prix():
    deals = [
        FauxDeal(position_id=42, entry=0, price=7584.71, profit=0.0, time_=100),
        FauxDeal(position_id=42, entry=1, price=7601.30, profit=159.28, time_=900),
    ]
    pnl, prix, sorties = PM._pnl_et_prix_sortie(deals, 42)
    assert len(sorties) == 1
    assert prix == 7601.30
    assert pnl == 159.28
    assert prix != 7584.71, "exit ne doit pas retomber sur entry"
    assert pnl != 0.0


def test_le_ticket_d_ordre_homonyme_ne_ramene_pas_l_entree():
    # Piege d'origine : la position N et son ordre d'ouverture portent le
    # meme numero, et l'ancien filtre acceptait `order == ticket`.
    deals = [FauxDeal(position_id=77, entry=0, price=100.0, profit=0.0,
                      time_=10, order=77)]
    assert PM._deals_de_sortie(deals, 77) == []


def test_clotures_partielles_cumulees_avec_frais():
    deals = [
        FauxDeal(position_id=9, entry=0, price=50.0, profit=0.0, time_=1),
        FauxDeal(position_id=9, entry=1, price=55.0, profit=30.0, time_=2,
                 commission=-1.5, swap=-0.5),
        FauxDeal(position_id=9, entry=1, price=58.0, profit=20.0, time_=3,
                 commission=-1.0, swap=0.0),
    ]
    pnl, prix, sorties = PM._pnl_et_prix_sortie(deals, 9)
    assert len(sorties) == 2
    assert prix == 58.0, "le prix retenu est celui du DERNIER deal de sortie"
    assert abs(pnl - 47.0) < 1e-9, "profit + commission + swap sur les 2 sorties"


def test_renversement_et_fermeture_par_opposee_comptent_comme_sorties():
    for code in (2, 3):           # INOUT, OUT_BY
        deals = [FauxDeal(position_id=5, entry=code, price=12.0, profit=3.0, time_=2)]
        pnl, prix, sorties = PM._pnl_et_prix_sortie(deals, 5)
        assert len(sorties) == 1 and prix == 12.0 and pnl == 3.0


def test_deal_d_une_autre_position_ignore():
    deals = [FauxDeal(position_id=111, entry=1, price=9.0, profit=5.0, time_=2)]
    pnl, prix, sorties = PM._pnl_et_prix_sortie(deals, 222)
    assert sorties == [] and pnl is None and prix is None


# ---------------------------------------------------------------------------
# Verification sur des clotures REELLES (data/deals_history.csv).
#
# Les tests ci-dessus utilisent des deals fabriques : ils prouvent que la
# fonction se comporte comme prevu sur les cas qu'on lui soumet, pas qu'elle
# se comporte comme prevu sur ce que le broker publie vraiment. Le defaut du
# 02/08 avait justement passe une suite verte avant d'echouer en production.
# Ce test rejoue l'historique reel du compte.
# ---------------------------------------------------------------------------
import collections
import csv
import os
from types import SimpleNamespace

import pytest

_HISTORIQUE = os.path.join("data", "deals_history.csv")


def _charger_deals_reels():
    par_position = collections.defaultdict(list)
    with open(_HISTORIQUE, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                d = SimpleNamespace(
                    time=int(r["time"]), symbol=r["symbol"], entry=int(r["entry"]),
                    price=float(r["price"]), profit=float(r["profit"]),
                    commission=float(r["commission"] or 0),
                    swap=float(r["swap"] or 0),
                    position_id=int(r["position_id"]), order=int(r["order"]))
            except (ValueError, KeyError, TypeError):
                continue
            par_position[d.position_id].append(d)
    return par_position


@pytest.mark.skipif(not os.path.exists(_HISTORIQUE),
                    reason="historique des deals absent de ce poste")
def test_clotures_reelles_donnent_exit_different_de_entry_et_pnl_non_nul():
    par_position = _charger_deals_reels()
    completes = [
        (pid, ds) for pid, ds in par_position.items()
        if any(d.entry == 0 for d in ds) and any(d.entry in (1, 2, 3) for d in ds)
    ]
    completes.sort(key=lambda kv: max(d.time for d in kv[1]), reverse=True)
    if len(completes) < 3:
        pytest.skip("moins de 3 clotures completes dans l'historique")

    tous = [d for ds in par_position.values() for d in ds]

    for pid, ds in completes[:6]:
        prix_entree = next(d.price for d in sorted(ds, key=lambda d: d.time)
                           if d.entry == 0)
        pnl, prix_sortie, sorties = PM._pnl_et_prix_sortie(tous, pid)

        assert sorties, "position %d : aucun deal de sortie retenu" % pid
        assert prix_sortie is not None, "position %d : exit vide" % pid
        assert abs(prix_sortie - prix_entree) > 1e-9, (
            "position %d : exit == entry (%.5f) — le deal d'entree a ete retenu"
            % (pid, prix_entree))
        assert pnl is not None and abs(pnl) > 1e-9, (
            "position %d : pnl nul, symptome exact du defaut du 02/08" % pid)


@pytest.mark.skipif(not os.path.exists(_HISTORIQUE),
                    reason="historique des deals absent de ce poste")
def test_temoin_l_ancien_critere_ramenait_bien_le_deal_d_entree():
    """
    Sans le filtre sur le type de deal, le premier deal rattache au ticket est
    l'ENTREE : profit nul et prix d'ouverture. C'est la mesure de production
    (5 lignes sur 5 avec pnl=0.0 et exit==entry) reproduite ici.
    """
    par_position = _charger_deals_reels()
    completes = [
        (pid, ds) for pid, ds in par_position.items()
        if any(d.entry == 0 for d in ds) and any(d.entry in (1, 2, 3) for d in ds)
    ]
    completes.sort(key=lambda kv: max(d.time for d in kv[1]), reverse=True)
    if len(completes) < 3:
        pytest.skip("moins de 3 clotures completes dans l'historique")

    for pid, ds in completes[:3]:
        premier = sorted(ds, key=lambda d: d.time)[0]
        assert premier.entry == 0
        assert premier.profit == 0.0, (
            "si le deal d'entree portait un profit, le defaut aurait ete visible")

