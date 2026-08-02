# -*- coding: utf-8 -*-
"""Environnement de test déterministe.

AJOUT 2026-07-30 (P1). Sans ce fichier, le résultat de la suite dépend des
variables d'environnement de la machine : `test_redaction` échoue si
EMPIRE_CONSOLE=0, `test_config_loader` échoue si MT5_PASSWORD est déjà défini.
Deux des sept échecs constatés lors de l'audit venaient de là, pas du code.
"""
import importlib.util
import os
from pathlib import Path

import pytest

# FIX 2026-08-02 : racine reelle du depot, independante du repertoire courant.
# La suite tourne desormais depuis un bac a sable temporaire
# (tools/valider_avant_demarrage.py) : tout test qui ouvre un fichier du depot
# par un chemin RELATIF echoue la-bas alors qu'il passe en local. C'est
# exactement ce qui est arrive a test_purge_masque_les_secrets_deja_ecrits.
DEPOT = Path(__file__).resolve().parent.parent

# Le module MetaTrader5 n'existe que sous Windows. Plusieurs defauts connus ne
# se manifestent QUE lorsqu'il est absent : le marqueur xfail correspondant
# doit donc etre conditionnel, sans quoi il produit des xpassed trompeurs sur
# la machine de production.
MT5_ABSENT = importlib.util.find_spec("MetaTrader5") is None


@pytest.fixture(scope="session")
def depot() -> Path:
    """Racine du depot. A utiliser des qu'un test lit un fichier du projet."""
    return DEPOT

# FIX 2026-07-30 (P1) — SECURITE.
# `tests/test_mt5_connection.py` n'est pas un test : c'est un diagnostic
# manuel (lancé par TEST_MT5_CONNECTION.bat). Sa fonction `test_fetch_and_
# paper_order` appelle `place_order("BTCUSD", lot=0.001, ORDER_TYPE_BUY)`,
# donc elle OUVRE UNE VRAIE POSITION dès que pytest la collecte sur une
# machine où MetaTrader5 est installé. Sous Linux elle échouait à l'import,
# ce qui masquait le danger ; sous Windows — et donc dans le garde-fou de
# démarrage — elle aurait passé un ordre au marché à chaque lancement.
# Le fichier est conservé tel quel, simplement exclu de la collecte.
collect_ignore = ["test_mt5_connection.py"]

_ENV_TEST = {
    "MT5_ACCOUNT": "12345678",
    "MT5_PASSWORD": "TestPass123",
    "MT5_SERVER": "Test-Demo",
    "TELEGRAM_BOT_TOKEN": "123456789:AAtesttesttesttesttesttesttesttest",
    "TELEGRAM_CHAT_ID": "1",
    "FINNHUB_API_KEY": "test",
    "ALPHA_VANTAGE_API_KEY": "test",
    "MT5_DRY_RUN": "1",
    "EMPIRE_CONSOLE": "1",      # requis par test_redaction
    "EMPIRE_LOG_LEVEL": "INFO",
}


@pytest.fixture(autouse=True, scope="session")
def _env_deterministe():
    anciens = {k: os.environ.get(k) for k in _ENV_TEST}
    os.environ.update(_ENV_TEST)
    yield
    for k, v in anciens.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
