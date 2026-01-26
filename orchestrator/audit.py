import json, os, time
from datetime import datetime, timezone

_AUDIT_PATH = "reports/audit_trades.jsonl"

def audit(event: str, payload: dict):
    os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload,
    }
    with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
