# tests/test_trade_events.py
import os, sys, types, json
from datetime import datetime, timezone, timedelta

# --- Bootstrap chemin projet ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from orchestrator.orchestrator import Orchestrator
from utils.position_manager import PositionManager

# --------- Test 1: #NEW_TRADE via Orchestrator._notify_trade_event (+ anti-spam) ---------
def test_new_trade_event_and_antispam(monkeypatch):
    o = Orchestrator(symbol="BTCUSD")
    # active un cooldown anti-spam
    o.profile.setdefault("orchestrator", {}).setdefault("anti_spam", {"cooldown_minutes": 5})
    sent = []
    # capture l'envoi Telegram
    monkeypatch.setattr(o, "_send_telegram", lambda text, kind, force: sent.append((text, kind, force)))

    payload = {
        "symbol": "BTCUSD",
        "side": "LONG",
        "entry": 50000.0,
        "sl": 49750.0,
        "tp": 50100.0,
        "lots": 0.010,
        "score": 0.72,
        "confluence": 3
    }
    # 1er envoi -> doit passer
    o._notify_trade_event("NEW_TRADE", payload)
    assert len(sent) == 1
    assert sent[-1][1] == "trade_event"
    assert sent[-1][0].startswith("#NEW_TRADE | BTCUSD | LONG | entry 50000.00")
    # 2e envoi identique dans la fenêtre -> bloqué par anti-spam
    o._notify_trade_event("NEW_TRADE", payload)
    assert len(sent) == 1  # pas de nouveau message

# --------- Test 2: #CLOSE_TRADE via PositionManager.detect (disparition ticket) ---------
def test_close_trade_event_from_position_manager(monkeypatch, tmp_path):
    # Prépare un PM avec notifier capturant les messages
    sent = []
    def notifier(tag, payload):
        sent.append((tag, payload))

    pm = PositionManager(mt5_client=None, symbol="XAUUSD", profile={}, notifier=notifier)

    # Utiliser un fichier d'état temporaire (évite d'écrire dans data/)
    pm._open_state_path = os.path.join(tmp_path, "open_positions.json")

    # État "précédent" = une position ouverte (ticket 111) — on la sauvegarde
    prev_state = {
        pm.symbol_canon: {
            "111": {
                "entry": 2000.0,
                "sl": 1995.0,
                "tp": 2005.0,
                "side": "BUY",
                "time": int(datetime.now(timezone.utc).timestamp()) - 3600,  # ouverte il y a 1h
            }
        }
    }
    os.makedirs(tmp_path, exist_ok=True)
    with open(pm._open_state_path, "w", encoding="utf-8") as f:
        json.dump(prev_state, f)

    # Stub mt5: plus aucune position en cours -> manage_open_positions doit détecter une fermeture
    def fake_positions_get():
        return []  # aucune position courante => le ticket 111 est "fermé"

    # Deals des dernières 48h: inclure la fermeture du ticket 111
    class Deal:
        def __init__(self, position_id, order, profit, price, ts_utc):
            self.position_id = position_id
            self.order = order
            self.profit = profit
            self.price = price
            self.time = ts_utc

    now_ts = int(datetime.now(timezone.utc).timestamp())
    # Fermeture avec +12.34 de profit à 2001.2
    close_deal = Deal(position_id=111, order=111, profit=12.34, price=2001.2, ts_utc=now_ts)

    def fake_history_deals_get(start, end):
        return [close_deal]

    class Info:
        point = 0.1  # pour calcul pips (ex: XAUUSD au point 0.1 selon broker)

    # Patch des fonctions MT5 utilisées dans PM
    monkeypatch.setattr("utils.position_manager.mt5", types.SimpleNamespace(
        history_deals_get=fake_history_deals_get,
        symbol_info=lambda s: Info()
    ), raising=False)

    # Patch de la méthode interne pour récupérer les positions en cours
    monkeypatch.setattr(pm, "_positions_get", fake_positions_get, raising=False)

    # Exécute la gestion — doit émettre #CLOSE_TRADE
    pm.manage_open_positions()

    # Vérifications
    # On s'attend à recevoir au moins un tag CLOSE_TRADE
    tags = [t for (t, p) in sent]
    assert "CLOSE_TRADE" in tags

    # Récupérer le payload et vérifier quelques champs
    payloads = [p for (t, p) in sent if t == "CLOSE_TRADE"]
    assert len(payloads) == 1
    p = payloads[0]
    assert p["symbol"] == "XAUUSD"
    assert p["ticket"] == 111
    assert p["pnl_ccy"].startswith("+")  # profit positif formaté
    # pips/durée sont calculés au mieux — on vérifie juste que les clés existent
    assert "pnl_pips" in p
    assert "duration" in p
