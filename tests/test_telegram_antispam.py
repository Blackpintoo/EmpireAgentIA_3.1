# tests/test_telegram_antispam.py
import os, sys
from datetime import datetime, timezone

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from orchestrator.orchestrator import Orchestrator

def test_antispam_basic(monkeypatch):
    o = Orchestrator(symbol="BTCUSD")
    # Simule une config avec cooldown 5 minutes
    o.profile.setdefault("orchestrator", {}).setdefault("anti_spam", {"cooldown_minutes": 5})
    sent = []
    monkeypatch.setattr(o, "_send_telegram", lambda text, kind, force: sent.append((text, kind, force)))

    msg = "#NEW_TRADE | BTCUSD | LONG | entry 50000.00 | 0.010 lots | SL 49500.00 | TP1 50100.00 | TP2 50200.00 | BE RR≥1.0"
    assert o._tg_antispam_ok("trade_event", msg) is True
    # 2e fois, même message dans la fenêtre de cooldown => rejet
    assert o._tg_antispam_ok("trade_event", msg) is False
