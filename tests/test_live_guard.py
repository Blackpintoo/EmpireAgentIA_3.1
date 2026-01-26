import os, json, pathlib, sys
from datetime import datetime, timezone, timedelta

# bootstrap
THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.live_metrics import AUDIT_PATH, rolling_metrics, should_allow_live

def _write_audit(tmp_path, rows):
    audit = tmp_path / "reports" / "audit_trades.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with open(audit, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return str(audit)

def test_allow_with_insufficient_sample(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    audit_path = _write_audit(tmp_path, [
        {"ts": now, "event":"CLOSE_TRADE","payload":{"symbol":"BTCUSD","profit_ccy": 10.0}},
    ])
    import utils.live_metrics as lm
    monkeypatch.setattr(lm, "AUDIT_PATH", audit_path, raising=False)
    ok, reason, m = should_allow_live("BTCUSD", {"min_trades_live": 5})
    assert ok and reason == "insufficient_sample"

def test_guard_blocks_when_pf_low(tmp_path, monkeypatch):
    # 12 trades dont 8 pertes => PF < 1
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(12):
        pnl = -10.0 if i < 8 else 20.0
        rows.append({"ts": (now - timedelta(hours=i)).isoformat(), "event":"CLOSE_TRADE",
                     "payload":{"symbol":"BTCUSD","profit_ccy": pnl}})
    audit_path = _write_audit(tmp_path, rows)
    import utils.live_metrics as lm
    monkeypatch.setattr(lm, "AUDIT_PATH", audit_path, raising=False)
    ok, reason, m = should_allow_live("BTCUSD", {"pf_min_live": 1.10, "min_trades_live": 5})
    assert not ok and reason.startswith("pf_live<")

def test_guard_blocks_when_hit_low(tmp_path, monkeypatch):
    # 10 trades: 3 wins, 7 losses => hit=0.3 < 0.45
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(10):
        pnl = 10.0 if i < 3 else -10.0
        rows.append({"ts": (now - timedelta(hours=i)).isoformat(), "event":"CLOSE_TRADE",
                     "payload":{"symbol":"BTCUSD","profit_ccy": pnl}})
    audit_path = _write_audit(tmp_path, rows)
    import utils.live_metrics as lm
    monkeypatch.setattr(lm, "AUDIT_PATH", audit_path, raising=False)
    ok, reason, m = should_allow_live("BTCUSD", {
        "hit_min_live": 0.45,
        "min_trades_live": 5,
        "pf_min_live": 0.0,   # <-- on neutralise PF pour tester le blocage sur hit-rate
    })
    assert not ok and reason.startswith("hit_live<")