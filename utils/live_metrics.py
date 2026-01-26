from __future__ import annotations
import os, json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Tuple

AUDIT_PATH = "reports/audit_trades.jsonl"
TZ = ZoneInfo("Europe/Zurich")

def _iter_audit():
    if not os.path.exists(AUDIT_PATH):
        return
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def _utc_to_local(ts_iso: str) -> datetime:
    # accepte ISOUTC '...Z' ou '...+00:00'
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return dt.astimezone(TZ)
    except Exception:
        return datetime.now(TZ)

def rolling_metrics(symbol: str, days: int = 7) -> Dict[str, Any]:
    """Calcule PF / HitRate / trades / pnl pour les N derniers jours (Europe/Zurich)."""
    cutoff = datetime.now(TZ) - timedelta(days=days)
    sym = symbol.upper()
    gross_win = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0
    trades = 0
    pnl = 0.0
    for rec in _iter_audit() or []:
        if rec.get("event") != "CLOSE_TRADE":
            continue
        p = rec.get("payload") or {}
        s = str(p.get("symbol") or "").upper()
        if s != sym:
            continue
        ts = _utc_to_local(rec.get("ts") or "")
        if ts < cutoff:
            continue
        # P&L en devise du compte (fallback sur autres clés)
        val = float(p.get("profit_ccy") or p.get("pnl_ccy") or p.get("pnl") or 0.0)
        trades += 1
        pnl += val
        if val >= 0:
            gross_win += val
            wins += 1
        else:
            gross_loss += abs(val)
            losses += 1
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    hit_rate = (wins / trades) if trades > 0 else 0.0
    return {
        "symbol": sym,
        "days": int(days),
        "pf": float(pf),
        "hit_rate": float(hit_rate),
        "trades": int(trades),
        "pnl": float(pnl),
        "gross_win": float(gross_win),
        "gross_loss": float(gross_loss),
        "wins": int(wins),
        "losses": int(losses),
    }

def should_allow_live(symbol: str, thresholds: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    thresholds attend:
      - pf_min_live (ex: 1.10)
      - hit_min_live (ex: 0.45)
      - min_trades_live (ex: 10) : exigence minimum d'échantillon
      - lookback_days (ex: 7)
    """
    lb = int(thresholds.get("lookback_days", 7))
    m = rolling_metrics(symbol, days=lb)
    # si peu de trades, on laisse passer (pas assez d'info)
    if m["trades"] < int(thresholds.get("min_trades_live", 10)):
        return True, "insufficient_sample", m
    if m["pf"] < float(thresholds.get("pf_min_live", 1.10)):
        return False, f"pf_live<{thresholds.get('pf_min_live')}", m
    if m["hit_rate"] < float(thresholds.get("hit_min_live", 0.45)):
        return False, f"hit_live<{thresholds.get('hit_min_live')}", m
    return True, "ok", m
