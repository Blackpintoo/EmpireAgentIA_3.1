# -*- coding: utf-8 -*-
"""
FIX 2026-08-02 — savoir si LE BOT tourne, et pas « un python quelconque ».

tools/purger_secrets_logs.py refusait d'agir des qu'un python.exe figurait
dans tasklist. Il a bloque la purge appelee depuis un test : pytest EST un
python.exe, le garde se declenchait donc sur le processus qui l'interrogeait.
En production, un notebook, un IDE ou un autre outil du depot auraient produit
le meme faux positif.
"""
import json
import os

import pytest

from utils import verrou_bot as VB


def test_sans_verrou_le_bot_est_considere_arrete(tmp_path):
    actif, pourquoi = VB.bot_actif(tmp_path / "bot.pid")
    assert actif is False
    assert "aucun verrou" in pourquoi


def test_un_pytest_qui_tourne_ne_declenche_plus_le_garde(tmp_path):
    """
    Le coeur du defaut : ce test EST execute par un python vivant. Sans
    verrou du bot, le garde doit malgre tout laisser passer.
    """
    actif, _ = VB.bot_actif(tmp_path / "bot.pid")
    assert actif is False, ("un processus python quelconque ne doit plus etre "
                            "pris pour le bot")


def test_verrou_vivant_bloque(tmp_path):
    chemin = tmp_path / "bot.pid"
    # PID 1 existe sur tout systeme POSIX ; sous Windows, on prend le notre,
    # mais bot_actif ignore volontairement son propre PID -> on simule.
    chemin.write_text(json.dumps({
        "pid": 1, "demarre_le": "2026-08-02T10:00:00Z", "point_entree": "main.py",
    }), encoding="utf-8")
    actif, pourquoi = VB.bot_actif(chemin)
    if os.name == "nt":
        pytest.skip("PID 1 n'a pas la meme semantique sous Windows")
    assert actif is True
    assert "PID 1" in pourquoi


def test_verrou_perime_est_ignore_et_retire(tmp_path):
    """Un arret brutal ne doit pas bloquer les outils pour toujours."""
    chemin = tmp_path / "bot.pid"
    chemin.write_text(json.dumps({"pid": 999_999_999}), encoding="utf-8")
    actif, pourquoi = VB.bot_actif(chemin)
    assert actif is False
    assert "perime" in pourquoi
    assert not chemin.exists(), "le verrou perime doit etre retire"


def test_le_processus_courant_ne_se_bloque_pas_lui_meme(tmp_path):
    chemin = tmp_path / "bot.pid"
    chemin.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    actif, _ = VB.bot_actif(chemin)
    assert actif is False


def test_poser_et_lever(tmp_path):
    chemin = tmp_path / "bot.pid"
    VB.poser_verrou(point_entree="test", chemin=chemin)
    assert chemin.exists()
    contenu = json.loads(chemin.read_text(encoding="utf-8"))
    assert contenu["pid"] == os.getpid()
    VB.lever_verrou(chemin)
    assert not chemin.exists()


def test_verrou_illisible_ne_bloque_pas(tmp_path):
    chemin = tmp_path / "bot.pid"
    chemin.write_text("{ pas du json", encoding="utf-8")
    actif, _ = VB.bot_actif(chemin)
    assert actif is False
