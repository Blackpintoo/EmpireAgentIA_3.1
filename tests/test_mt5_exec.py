# tests/test_mt5_exec.py
import os, sys, types

# --- Bootstrap chemin projet ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.mt5_client import MT5Client

def test_invalid_volume_then_ok(monkeypatch):
    # Désactive l'init/login réels pendant le test
    monkeypatch.setattr(MT5Client, "_ensure_initialized_and_login", lambda self: None, raising=False)
    MT5Client._initialized = True
    MT5Client._logged_in = True

    # Stub info symbole
    class Info:
        volume_min = 0.01
        volume_max = 1.0
        volume_step = 0.01
        point = 0.01
        stops_level = 0
        visible = True

    tick = types.SimpleNamespace(bid=49999.0, ask=50001.0)
    STATE = {"calls": 0}
    DONE = 10009
    INVALID_VOLUME = 10030

    def order_send(req):
        STATE["calls"] += 1
        # 1er appel : volume pas aligné -> INVALID_VOLUME
        if STATE["calls"] == 1:
            return types.SimpleNamespace(retcode=INVALID_VOLUME, order=None, deal=None)
        return types.SimpleNamespace(retcode=DONE, order=123456, deal=654321)

    # Stub complet de mt5 pour ce test
    monkeypatch.setattr(
        "utils.mt5_client.mt5",
        types.SimpleNamespace(
            ORDER_TYPE_BUY=0,
            ORDER_TYPE_SELL=1,
            TRADE_ACTION_DEAL=1,
            TRADE_RETCODE_DONE=DONE,
            TRADE_RETCODE_INVALID_VOLUME=INVALID_VOLUME,
            order_send=order_send,
            symbol_info=lambda s: Info(),
            symbol_select=lambda s, v: True,
            symbol_info_tick=lambda s: tick,
        ),
        raising=False,
    )

    c = MT5Client()
    # Config d'exécution réduite pour tests (pas d'attente)
    c.cfg.setdefault("execution", {"max_retries": 3, "backoff_seconds": [0, 0, 0], "slippage_points": 5})

    # volume légèrement off-step -> ajustement sur retry
    res = c.place_order("BTCUSD", "BUY", 0.0105, price=50000, sl=49950, tp=50050, comment="test")
    assert res.get("ok") is True
    assert res.get("order") == 123456

def test_requote_refresh_price(monkeypatch):
    # Désactive l'init/login réels pendant le test
    monkeypatch.setattr(MT5Client, "_ensure_initialized_and_login", lambda self: None, raising=False)
    MT5Client._initialized = True
    MT5Client._logged_in = True

    PRICE_CHANGED = 10032
    REQUOTE = 10031
    DONE = 10009

    class Info:
        volume_min = 0.01
        volume_max = 1.0
        volume_step = 0.01
        point = 0.01
        stops_level = 0
        visible = True

    ticks = [
        types.SimpleNamespace(bid=2000.0, ask=2000.5),
        types.SimpleNamespace(bid=2001.0, ask=2001.5),
    ]
    calls = {"n": 0}

    def order_send(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return types.SimpleNamespace(retcode=REQUOTE, order=None, deal=None)
        return types.SimpleNamespace(retcode=DONE, order=42, deal=24)

    def symbol_info_tick(_):
        return ticks[min(calls["n"] - 1, len(ticks) - 1)]

    # Stub complet de mt5 pour ce test
    monkeypatch.setattr(
        "utils.mt5_client.mt5",
        types.SimpleNamespace(
            ORDER_TYPE_BUY=0,
            ORDER_TYPE_SELL=1,
            TRADE_ACTION_DEAL=1,
            TRADE_RETCODE_DONE=DONE,
            TRADE_RETCODE_REQUOTE=REQUOTE,
            TRADE_RETCODE_PRICE_CHANGED=PRICE_CHANGED,
            order_send=order_send,
            symbol_info=lambda s: Info(),
            symbol_select=lambda s, v: True,
            symbol_info_tick=symbol_info_tick,
        ),
        raising=False,
    )

    c = MT5Client()
    c.cfg.setdefault("execution", {"max_retries": 3, "backoff_seconds": [0, 0, 0], "price_refresh_on_requote": True})
    res = c.place_order("XAUUSD", "BUY", 0.05, price=2000.0, sl=1995.0, tp=2005.0, comment="rq")
    assert res.get("ok") is True
    assert res.get("order") == 42
