# -*- coding: utf-8 -*-
"""
FIX 2026-08-02 — deux defauts qui ont fait disparaitre l'etat d'une position
reelle (SP500 ticket 1690929973, ouverte 61 h sans gestion).

D1 : un unique cycle ou MT5 renvoie 0 position supprimait definitivement
     l'entree pm_state du ticket.
D2 : 12 PositionManager partagent data/pm_state.json ; chacun reecrivait le
     fichier entier depuis une copie memoire figee a la construction, donc
     ecrasait les entrees creees entre-temps par les autres symboles.
"""
import json

import pytest

import utils.position_manager as PM


@pytest.fixture
def etat_temporaire(tmp_path, monkeypatch):
    chemin = tmp_path / "pm_state.json"
    monkeypatch.setattr(PM, "_STATE_PATH", str(chemin))
    return chemin


def test_fusion_preserve_les_cles_des_autres_symboles(etat_temporaire):
    """Le coeur de D2 : deux ecrivains, aucune perte."""
    PM.fusionner_etat(maj={"SP500:111": {"sl_orig": 7476.76}})
    # Un second PositionManager, dont la copie memoire ignore SP500 :
    PM.fusionner_etat(maj={"BTCUSD:222": {"sl_orig": 63134.93}})

    disque = json.loads(etat_temporaire.read_text(encoding="utf-8"))
    assert "SP500:111" in disque, "l'entree SP500 a ete ecrasee"
    assert "BTCUSD:222" in disque


def test_ancien_comportement_aurait_perdu_la_cle(etat_temporaire):
    """Temoin : l'ecrasement global, lui, perd bien l'entree."""
    PM.fusionner_etat(maj={"SP500:111": {"sl_orig": 7476.76}})
    copie_memoire_perimee = {"BTCUSD:222": {"sl_orig": 63134.93}}
    PM._save_state(copie_memoire_perimee)          # ancien chemin

    disque = json.loads(etat_temporaire.read_text(encoding="utf-8"))
    assert "SP500:111" not in disque   # c'est exactement ce qui s'est produit


def test_fusion_supprime_uniquement_les_cles_demandees(etat_temporaire):
    PM.fusionner_etat(maj={"SP500:111": {}, "BTCUSD:222": {}, "NAS100:333": {}})
    PM.fusionner_etat(suppressions=["SP500:111"])

    disque = json.loads(etat_temporaire.read_text(encoding="utf-8"))
    assert set(disque) == {"BTCUSD:222", "NAS100:333"}


def test_fusion_survit_a_un_fichier_illisible(etat_temporaire):
    etat_temporaire.write_text("{ ceci n'est pas du json", encoding="utf-8")
    PM.fusionner_etat(maj={"BTCUSD:222": {"sl_orig": 1.0}})
    disque = json.loads(etat_temporaire.read_text(encoding="utf-8"))
    assert "BTCUSD:222" in disque


def test_seuil_absences_configure():
    """D1 : une seule lecture vide ne doit plus suffire."""
    assert PM._ABSENCES_AVANT_CLOTURE >= 2, (
        "une lecture MT5 vide isolee suffirait a declarer une position fermee")
