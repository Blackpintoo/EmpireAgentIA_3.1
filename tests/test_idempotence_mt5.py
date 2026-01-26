import types, sys, os, time
THIS_DIR = os.path.dirname(__file__); PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)

from utils.mt5_client import MT5Client

def test_duplicate_order_suppressed(monkeypatch):
    # stub mt5
    DONE=10009
    calls = {"n":0}
    def order_send(req):
        calls["n"]+=1
        return types.SimpleNamespace(retcode=DONE, order=1, deal=1)
    monkeypatch.setattr("utils.mt5_client.mt5", types.SimpleNamespace(
        ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, TRADE_ACTION_DEAL=1,
        TRADE_RETCODE_DONE=DONE, order_send=order_send, symbol_info=lambda s: types.SimpleNamespace(volume_step=0.01, volume_min=0.01, point=0.01, stops_level=0, visible=True),
        symbol_select=lambda s,v: True, symbol_info_tick=lambda s: types.SimpleNamespace(bid=100.0, ask=100.1)
    ), raising=False)
    c = MT5Client()
    c.cfg.setdefault("execution", {"max_retries": 1, "backoff_seconds": [0], "slippage_points": 5})
    r1 = c.place_order("BTCUSD","BUY",0.05,price=100.1,sl=99.0,tp=101.0,comment="dup")
    r2 = c.place_order("BTCUSD","BUY",0.05,price=100.1,sl=99.0,tp=101.0,comment="dup")
    assert r1.get("ok") is True
    assert r2.get("ok") is False and r2.get("error") == "duplicate_order_suppressed"
