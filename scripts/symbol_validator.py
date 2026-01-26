# scripts/symbol_validator.py
from __future__ import annotations
import os, sys, json, argparse
from typing import Any, Dict, Optional

# Bootstrap chemin projet
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import yaml

try:
    # charge .env si dispo (ne casse pas si absent)
    from config_loader import load_dotenv_env # type: ignore
except Exception:
    def load_dotenv_env(*args, **kwargs): return {}

# MT5 client & module natif
from utils import mt5_client as mt5c
mt5 = mt5c.mt5

def _load_yaml(path: str) -> Dict[str, Any]:
    if not os.path.exists(path): return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _get_profile(profiles: Dict[str, Any], overrides: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    base = (profiles.get(symbol) or {}).copy()
    ov_g = (overrides.get("GLOBAL") or {})
    ov_s = (overrides.get(symbol) or {})
    # merge simple : GLOBAL puis symbole
    def deep_merge(a, b):
        if not isinstance(a, dict) or not isinstance(b, dict):
            return b if b is not None else a
        out = a.copy()
        for k, v in b.items():
            out[k] = deep_merge(out.get(k), v)
        return out
    out = deep_merge(base, ov_g)
    out = deep_merge(out, ov_s)
    return out or {}

def _extract_expected(profile: Dict[str, Any]) -> Dict[str, Any]:
    inst = profile.get("instrument") or {}
    brok = profile.get("broker") or {}
    return {
        "broker_symbol": (brok.get("symbol") or inst.get("broker_symbol") or "").strip(),
        "digits": inst.get("digits"),
        "point": inst.get("point"),
        "contract_size": inst.get("contract_size"),
        "lot_min": inst.get("lot_min"),
        "lot_step": inst.get("lot_step"),
        "stops_level": inst.get("stops_level"),
    }

def _extract_actual(broker_symbol: str) -> Dict[str, Any]:
    if not broker_symbol:
        return {"error": "missing_broker_symbol"}
    if not mt5c.MT5Client._initialized:
        mt5c.MT5Client._initialize_if_needed()
    # sélectionner le symbole
    mt5.symbol_select(broker_symbol, True)
    info = mt5.symbol_info(broker_symbol)
    if not info:
        return {"error": "symbol_info_none"}
    return {
        "visible": bool(getattr(info, "visible", False)),
        "digits": int(getattr(info, "digits", 0)),
        "point": float(getattr(info, "point", 0.0) or 0.0),
        "contract_size": float(getattr(info, "trade_contract_size", 0.0) or 0.0),
        "lot_min": float(getattr(info, "volume_min", 0.0) or 0.0),
        "lot_step": float(getattr(info, "volume_step", 0.0) or 0.0),
        "lot_max": float(getattr(info, "volume_max", 0.0) or 0.0),
        "stops_level": int(getattr(info, "stops_level", 0) or 0),
        "freeze_level": int(getattr(info, "freeze_level", 0) or 0),
        "trade_mode": int(getattr(info, "trade_mode", 0) or 0),
        "margin_initial": float(getattr(info, "margin_initial", 0.0) or 0.0),
    }

def compare(symbol: str, expected: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    out = {"symbol": symbol, "ok": True, "diffs": []}
    if "error" in actual:
        out["ok"] = False
        out["diffs"].append({"field": "symbol_info", "expected": expected, "actual": actual})
        return out
    checks = ["digits", "point", "contract_size", "lot_min", "lot_step", "stops_level"]
    for k in checks:
        ev = expected.get(k)
        av = actual.get(k)
        # tolérance flottants
        if isinstance(ev, float):
            eq = (abs((av or 0.0) - ev) <= 1e-12)
        else:
            eq = (av == ev)
        if ev is not None and not eq:
            out["ok"] = False
            out["diffs"].append({"field": k, "expected": ev, "actual": av})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="profiles.yaml")
    ap.add_argument("--overrides", default="overrides.yaml")
    ap.add_argument("--symbols", nargs="*", default=["BTCUSD","XAUUSD","ETHUSD","LNKUSD","EURUSD","BNBUSD"])
    ap.add_argument("--json", action="store_true", help="Sortie JSON")
    args = ap.parse_args()

    # env & MT5 init/login (tolérant aux variantes de MT5Client)
    load_dotenv_env("config/.env", extra_paths=("config/.env.local",), overwrite=False)
    # 1) initialize
    try:
        # variante la plus fréquente dans ton code
        mt5c.MT5Client._initialize_if_needed()  # type: ignore[attr-defined]
    except Exception:
        try:
            # autre variante (si décorée @classmethod)
            mt5c.MT5Client.initialize_if_needed()  # type: ignore[attr-defined]
        except Exception:
            pass
    # 2) login
    try:
        mt5c.MT5Client.login_if_needed()
    except Exception:
        pass
    # 3) fallback: instanciation (déclenche souvent init+login via __init__)
    try:
        if not getattr(mt5c.MT5Client, "_logged_in", False):
            mt5c.MT5Client()
    except Exception:
        pass

    profiles = _load_yaml(args.profiles)
    overrides = _load_yaml(args.overrides)

    results = []
    for sym in args.symbols:
        prof = _get_profile(profiles, overrides, sym)
        exp = _extract_expected(prof)
        # fallback broker symbol = même que canonique si non fourni
        if not exp["broker_symbol"]:
            exp["broker_symbol"] = sym
        act = _extract_actual(exp["broker_symbol"])
        res = compare(sym, exp, act)
        res["broker_symbol"] = exp["broker_symbol"]
        res["actual"] = act
        results.append(res)

    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        # joli rendu console
        for r in results:
            status = "OK" if r["ok"] else "MISMATCH"
            print(f"{r['symbol']:7s} ↔ {r['broker_symbol']:>12s} | {status}")
            if not r["ok"]:
                for d in r["diffs"]:
                    print(f"  - {d['field']}: expected={d['expected']} actual={d['actual']}")
            # quelques champs utiles à visualiser
            a = r["actual"]
            if "error" not in a:
                print(f"    digits={a['digits']} point={a['point']} lot_min={a['lot_min']} lot_step={a['lot_step']} stops={a['stops_level']}")
        # code de retour non zéro si un symbole est KO
        if any(not r["ok"] for r in results):
            sys.exit(2)

if __name__ == "__main__":
    main()
