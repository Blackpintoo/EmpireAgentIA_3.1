# -*- coding: utf-8 -*-
"""
FIX 2026-08-02 — trade_mfe.csv documentait la trajectoire mais pas l'issue.

Mesure sur le journal de production : `pnl` valait 0.0 sur 8 lignes sur 8 et
`exit` etait vide sur 5 sur 8, parce que la ligne etait ecrite des la
detection de la cloture, avant que MT5 n'ait publie le deal.
"""
import csv
from types import SimpleNamespace

import pytest

import utils.position_manager as PM


class _PMFactice:
    """Le strict necessaire pour exercer l'ecriture du journal."""
    _MFE_COLONNES = PM.PositionManager._MFE_COLONNES
    _mfe_migrer_entete = PM.PositionManager._mfe_migrer_entete
    _log_mfe_row = PM.PositionManager._log_mfe_row
    _resoudre_clotures_en_attente = PM.PositionManager._resoudre_clotures_en_attente

    def __init__(self, chemin):
        self.symbol_canon = "SP500"
        self._chemin = chemin
        self._clotures_en_attente = {}

    def _mfe_chemin(self):
        return str(self._chemin)


def _lignes(chemin):
    with open(chemin, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_ligne_ecrite_avec_pnl_et_exit(tmp_path):
    pm = _PMFactice(tmp_path / "trade_mfe.csv")
    pm._log_mfe_row(111, "BUY", 7462.97, 7497.48, 507.30, 1.96, -0.26,
                    {"sl_orig": 7446.3}, resolu=True)
    (r,) = _lignes(pm._chemin)
    assert r["pnl"] == "507.3"
    assert r["exit"] == "7497.48"
    assert r["resolu"] == "True"


def test_cloture_sans_deal_est_differee_puis_resolue(tmp_path):
    pm = _PMFactice(tmp_path / "trade_mfe.csv")
    pm._clotures_en_attente[111] = {
        "side": "BUY", "entry": 7462.97, "mfe": 1.96, "mae": -0.26,
        "st": {"sl_orig": 7446.3}, "essais": 0,
    }
    # Cycle 1 : MT5 n'a pas encore publie le deal -> rien n'est ecrit.
    pm._resoudre_clotures_en_attente([])
    assert not pm._chemin.exists()
    assert 111 in pm._clotures_en_attente

    # Cycle 2 : seul le deal d'ENTREE est publie -> toujours rien.
    # MAJ 2026-08-04 : c'est le cas qui produisait pnl=0.0 et exit==entry en
    # production. Un deal d'entree porte entry=0 (DEAL_ENTRY_IN), un profit
    # nul et le prix d'ouverture ; il ne resout pas une cloture.
    entree = SimpleNamespace(position_id=111, order=111, entry=0, profit=0.0,
                             price=7462.97, time=100)
    pm._resoudre_clotures_en_attente([entree])
    assert not pm._chemin.exists()
    assert 111 in pm._clotures_en_attente

    # Cycle 3 : le deal de SORTIE apparait -> la ligne est ecrite, complete.
    deal = SimpleNamespace(position_id=111, order=0, entry=1, profit=507.30,
                           price=7497.48, time=900)
    pm._resoudre_clotures_en_attente([entree, deal])
    (r,) = _lignes(pm._chemin)
    assert r["pnl"] == "507.3" and r["exit"] == "7497.48" and r["resolu"] == "True"
    assert not pm._clotures_en_attente


def test_abandon_apres_trop_de_cycles_marque_la_ligne_non_resolue(tmp_path):
    pm = _PMFactice(tmp_path / "trade_mfe.csv")
    pm._clotures_en_attente[111] = {
        "side": "BUY", "entry": 7462.97, "mfe": 1.96, "mae": -0.26,
        "st": {}, "essais": PM._MFE_ATTENTE_MAX_CYCLES - 1,
    }
    pm._resoudre_clotures_en_attente([])
    (r,) = _lignes(pm._chemin)
    assert r["resolu"] == "False"
    assert r["pnl"] == "" and r["exit"] == ""
    assert not pm._clotures_en_attente, "la cloture ne doit pas rester en attente"


def test_migration_ajoute_la_colonne_sans_perdre_de_lignes(tmp_path):
    ancien = tmp_path / "trade_mfe.csv"
    ancien.write_text(
        "ts_utc,symbol,ticket,side,entry,exit,pnl,mfe_r,mae_r,sl_orig,be_done,trail_active\n"
        "2026-07-31T09:36:09+00:00,AUDUSD,1687139804,BUY,0.70318,,0.0,1.1584,-0.4059,0.70217,True,False\n",
        encoding="utf-8")
    pm = _PMFactice(ancien)
    pm._log_mfe_row(222, "SELL", 1.0, 0.9, -10.0, 0.1, -1.0, {}, resolu=True)

    lignes = _lignes(ancien)
    assert len(lignes) == 2, "la ligne historique a ete perdue"
    assert lignes[0]["resolu"] == "False"   # on ignore si son P&L etait connu
    assert lignes[1]["resolu"] == "True"
