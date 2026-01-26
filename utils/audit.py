# utils/audit.py
import os, json
from datetime import datetime
from typing import Dict, Any

_BASE = os.path.join(os.getcwd(), "data", "audit")

def _ensure_dir():
    try:
        os.makedirs(_BASE, exist_ok=True)
    except Exception:
        pass

def _today_path() -> str:
    d = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(_BASE, f"audit_{d}.jsonl")

def log_audit(event: str, payload: Dict[str, Any]):
    """
    Écrit une ligne JSONL dans data/audit/audit_YYYY-MM-DD.jsonl
    """
    _ensure_dir()
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **(payload or {})}
    path = _today_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path

def append(event: str, payload: Dict[str, Any]):
    """
    Alias rétro-compatible pour log_audit() afin d'éviter les ImportError legacy.
    """
    return log_audit(event, payload)
