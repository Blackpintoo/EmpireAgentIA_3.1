# tests/test_daily_digest.py
import os, sys, types
from datetime import datetime, timezone, timedelta

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reporting.daily_digest import generate_daily_digest, send_daily_digest

class Deal:
    def __init__(self, symbol, profit, ts_utc):
        self.symbol = symbol
        self.profit = profit
        self.time = ts_utc

def test_generate_and_send_digest(monkeypatch):
    # Stub deals du jour (UTC timestamps dans la plage)
    now = datetime.now(timezone.utc).timestamp()
    fake_deals = [
        Deal("BTCUSD", +120.0, now - 3600),
        Deal("BTCUSD", -50.0,  now - 1800),
        Deal("XAUUSD", +30.0,  now - 600),
    ]
    def fake_history_deals_get(start, end):
        s, e = start.timestamp(), end.timestamp()
        return [d for d in fake_deals if s <= d.time <= e]

    # Patch mt5 dans le module de digest
    import reporting.daily_digest as dd
    dd.mt5 = types.SimpleNamespace(history_deals_get=fake_history_deals_get)

    text = generate_daily_digest(["BTCUSD","XAUUSD"], tz_name="Europe/Zurich")
    assert "#DAILY_DIGEST" in text
    assert "P&L +100.00" in text  # 120 - 50 + 30 = +100
    assert "trades 3" in text
    # Envoi
    sent = {"msg": None}
    def fake_send(text, kind="daily_digest", force=True):
        sent["msg"] = (text, kind, force)
    ok = send_daily_digest(fake_send, ["BTCUSD","XAUUSD"], tz_name="Europe/Zurich")
    assert ok is True
    assert sent["msg"][1] == "daily_digest"
