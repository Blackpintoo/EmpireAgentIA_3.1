import os, sys, json, pathlib
from datetime import datetime, timezone

# --- bootstrap chemin projet ---
THIS_FILE = pathlib.Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def test_daily_digest(tmp_path, monkeypatch):
    # 1) Neutraliser l'init MT5 pendant le test
    from utils.mt5_client import MT5Client
    monkeypatch.setattr(MT5Client, "initialize_if_needed", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(MT5Client, "login_if_needed", classmethod(lambda cls, cfg=None: None), raising=False)
    monkeypatch.setattr(MT5Client, "_ensure_initialized_and_login", lambda self: None, raising=False)
    MT5Client._initialized = True
    MT5Client._logged_in = True

    # 2) Préparer un répertoire temporaire pour l'audit
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    audit_file = reports_dir / "audit_trades.jsonl"

    # Deux trades fermés aujourd'hui (UTC)
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {"ts": now, "event": "CLOSE_TRADE", "payload": {"symbol": "BTCUSD", "profit_ccy": 50.0}},
        {"ts": now, "event": "CLOSE_TRADE", "payload": {"symbol": "XAUUSD", "profit_ccy": -20.0}},
    ]
    with audit_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    # 3) Pointer utils.digest vers notre fichier temporaire
    import utils.digest as digest_mod
    monkeypatch.setattr(digest_mod, "AUDIT_PATH", str(audit_file), raising=False)

    # 4) Capturer les envois Telegram et appeler _send_daily_digest()
    from orchestrator.orchestrator import Orchestrator
    sent = []
    o = Orchestrator(symbol="BTCUSD")
    monkeypatch.setattr(o, "_send_telegram", lambda txt, **kw: sent.append(txt), raising=False)

    o._send_daily_digest()

    # 5) Assertions
    assert sent, "Aucun message digest n'a été envoyé"
    digest_msg = sent[0]
    assert "BTCUSD" in digest_msg and "XAUUSD" in digest_msg
    assert "50.00" in digest_msg or "50" in digest_msg
    assert "-20.00" in digest_msg or "-20" in digest_msg
