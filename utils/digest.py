# utils/digest.py
from __future__ import annotations
import os, json
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from typing import Dict, Any

AUDIT_PATH = "reports/audit_trades.jsonl"
TZ = ZoneInfo("Europe/Zurich")

def _iter_audit():
    if not os.path.exists(AUDIT_PATH):
        return
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def daily_digest_for(date_yyyymmdd: str) -> Dict[str, Any]:
    # format attendu: "YYYY-MM-DD" en Europe/Zurich
    out = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
    total = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
    for rec in _iter_audit():
        ts = rec.get("ts")
        if not ts: 
            continue
        try:
            dt_utc = datetime.fromisoformat(ts.replace("Z","+00:00"))
        except Exception:
            continue
        dt_local = dt_utc.astimezone(TZ)
        ymd = dt_local.strftime("%Y-%m-%d")
        if ymd != date_yyyymmdd:
            continue
        ev = rec.get("event"); p = rec.get("payload") or {}
        if ev == "CLOSE_TRADE":
            sym = (p.get("symbol") or "").upper()
            pnl = float(p.get("profit_ccy") or p.get("pnl_ccy") or p.get("pnl") or 0.0)
            out[sym]["pnl"] += pnl
            out[sym]["trades"] += 1
            if pnl >= 0: out[sym]["wins"] += 1
            else: out[sym]["losses"] += 1
            total["pnl"] += pnl
            total["trades"] += 1
            if pnl >= 0: total["wins"] += 1
            else: total["losses"] += 1
    return {"by_symbol": dict(out), "total": total}

def format_digest_message(digest: Dict[str, Any], date_yyyymmdd: str) -> str:
    total = digest.get("total", {})
    lines = [f"[DIGEST] Resume {date_yyyymmdd} (Europe/Zurich)"]
    by = digest.get("by_symbol", {})
    for sym, m in sorted(by.items()):
        lines.append(f"- {sym}: P&L={m['pnl']:.2f} | trades={m['trades']} (W:{m['wins']}/L:{m['losses']})")
    lines.append("-")
    lines.append(f"Total: P&L={total.get('pnl',0.0):.2f} | trades={total.get('trades',0)} (W:{total.get('wins',0)}/L:{total.get('losses',0)})")
    return "\n".join(lines)
