from __future__ import annotations
import os, json, csv
from pathlib import Path
from typing import Dict, Any, Optional
from utils.config import load_config  # pour lire backtest.gating (synonymes)

DEFAULT_THRESHOLDS = {
    "pf_min": 1.30,
    "maxdd_max": 0.12,       # 12%
    "expectancy_min": 0.0,
    "rr_min": 1.50,
    "min_trades": 200,
}

_KEY_MAP = {
    "maxdd_pct_max": "maxdd_max",
    "rr_proxy_min": "rr_min",
}

def _norm_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k,v in (d or {}).items():
        out[_KEY_MAP.get(k,k)] = v
    return out

def load_thresholds_for(symbol: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    th = dict(DEFAULT_THRESHOLDS)
    try:
        cfg = load_config() or {}
        g = (((cfg.get("backtest") or {}).get("gating")) or {})
        th.update(_norm_keys(g))
    except Exception:
        pass
    if overrides:
        th.update(_norm_keys(overrides))
    return th

def _safe_float(x) -> float:
    try: return float(x)
    except Exception: return 0.0

def _load_json_metrics(p: Path) -> Optional[Dict[str, Any]]:
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(m, dict) and isinstance(m.get("metrics"), dict):
            m = m.get("metrics") or {}
        # accepte *_gating.json ou *_summary.json
        return {
            "profit_factor": _safe_float(m.get("profit_factor") or m.get("pf") or 0),
            "max_drawdown":  _safe_float(m.get("max_drawdown")  or m.get("maxdd") or m.get("maxdd_pct") or 0),
            "expectancy":    _safe_float(m.get("expectancy")    or 0),
            "avg_rr":        _safe_float(m.get("avg_rr")        or m.get("rr") or m.get("rr_proxy") or 0),
            "n_trades":      int(m.get("n_trades") or m.get("trades") or 0),
            "sharpe":        _safe_float(m.get("sharpe") or 0),
        }
    except Exception:
        return None

def _load_csv_metrics(p: Path) -> Optional[Dict[str, Any]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows: return None
        last = rows[-1]
        return {
            "profit_factor": _safe_float(last.get("profit_factor") or last.get("PF")),
            "max_drawdown":  _safe_float(last.get("max_drawdown")  or last.get("MaxDD")),
            "expectancy":    _safe_float(last.get("expectancy")    or last.get("Exp")),
            "avg_rr":        _safe_float(last.get("avg_rr")        or last.get("RR")),
            "n_trades":      int(_safe_float(last.get("trades")    or last.get("N"))),
            "sharpe":        _safe_float(last.get("sharpe")        or 0),
        }
    except Exception:
        return None

def find_latest_metrics(report_dir: str, symbol: str) -> Optional[Dict[str, Any]]:
    p = Path(report_dir)
    cands = sorted(list(p.rglob(f"*{symbol}*gating.json")) + list(p.rglob(f"*{symbol}*summary.json")),
                   key=lambda x: x.stat().st_mtime, reverse=True)
    for c in cands:
        m = _load_json_metrics(c)
        if m: return m
    # fallback CSV
    cands = sorted(p.rglob(f"*{symbol}*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    for c in cands:
        m = _load_csv_metrics(c)
        if m: return m
    return None
# --- Compatibilité ascendante ---
def _find_latest_metrics(report_dir: str, symbol: str):
    # alias pour l'ancien import
    return find_latest_metrics(report_dir, symbol)

def should_allow_trade(symbol: str, thresholds: Dict[str, Any], metrics: Optional[Dict[str, Any]] = None, report_dir: str = "reports/backtests"):
    m = metrics or find_latest_metrics(report_dir, symbol)
    if not m:
        if bool(thresholds.get("allow_no_report", False)):
            return True, "no_report_allowed", {}
        return False, "no_report", {}
    # ---------------------------------------------------
    if m.get("n_trades", 0) < int(thresholds.get("min_trades", 0)):
        return False, "min_trades", m
    if m.get("profit_factor", 0.0) < float(thresholds.get("pf_min", 0)):
        return False, "pf", m
    if m.get("max_drawdown", 1.0) > float(thresholds.get("maxdd_max", 1)):
        return False, "maxdd", m
    if m.get("expectancy", -1e9) < float(thresholds.get("expectancy_min", 0)):
        return False, "exp", m
    if m.get("avg_rr", 0.0) < float(thresholds.get("rr_min", 0)):
        return False, "rr", m
    return True, "ok", m

