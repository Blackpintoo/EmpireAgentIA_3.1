# scripts/run_agents.py — envoie un petit ordre MT5 (si dry_run:false), sinon écrit #NEW_TRADE_SIM
import sys, pathlib, random, json
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml

def now_iso(): return datetime.now(timezone.utc).isoformat()

def load_symbols_cfg():
    cfg = yaml.safe_load((ROOT/"config/profiles.yaml").read_text(encoding="utf-8"))
    syms = cfg.get("enabled_symbols") or ["BTCUSD","ETHUSD"]
    profs = cfg.get("profiles") or {}
    return syms, profs

def load_overrides(path="config/presets/overrides.live.yaml"):
    if not (ROOT/path).exists():
        path = "config/presets/overrides.demo.yaml"
    try:
        return yaml.safe_load((ROOT/path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def audit_write(rec):
    logs = ROOT/"logs"; logs.mkdir(parents=True, exist_ok=True)
    with (logs/"audit_trades.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False)+"\n")

def main():
    syms, profs = load_symbols_cfg()
    ov = load_overrides()
    dry_run = bool((((ov.get("GLOBAL") or {}).get("execution") or {}).get("dry_run", True)))

    # 15% de chance d'envoyer un ordre/écriture à chaque tick (60s)
    if random.random() > 0.40:
        print("[agents] no signal")
        return 0
    symbol = random.choice(syms)
    side = random.choice(["BUY","SELL"])

    # risques basés profils
    prof = profs.get(symbol, {})
    r = (prof.get("risk") or {})
    risk_pct = float(r.get("risk_per_trade", 0.005))

    if dry_run:
        rec = {"ts": now_iso(),"type":"#NEW_TRADE_SIM","symbol":symbol,"side":side,
               "risk_pct":risk_pct,"rr_target":1.8,"reason":"agent_signal","demo":True}
        audit_write(rec)
        print(f"[agents] dry_run new trade {symbol} {side}")
        return 0

    # --- Envoi d’un ordre MT5 ---
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            print("[agents] MT5 init failed", mt5.last_error()); return 2

        broker_symbol = ((prof.get("instrument") or {}).get("broker_symbol")) or symbol
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            print(f"[agents] symbol_info_none: {broker_symbol}"); return 2

        lot = max(float(getattr(info, "volume_min", 0.01) or 0.01), 0.01)

        price = info.ask if side=="BUY" else info.bid
        if not price:
            tick = mt5.symbol_info_tick(broker_symbol)
            price = tick.ask if side=="BUY" else tick.bid
        if not price:
            print("[agents] no price"); return 2

        point = info.point or 0.01
        sl_dist = price * 0.005         # ≈0.5%
        tp_dist = sl_dist * 1.8         # RR ~ 1.8
        sl = price - sl_dist if side=="BUY" else price + sl_dist
        tp = price + tp_dist if side=="BUY" else price - tp_dist

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 91001,
            "comment": "empire.agent.live_demo",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        audit_write({"ts": now_iso(),"type":"#NEW_TRADE","symbol":symbol,"side":side,
                     "risk_pct":risk_pct,"reason":"agent_signal","mt5_request":req,"mt5_result":str(res)})
        print(f"[agents] sent {symbol} {side} -> retcode={getattr(res,'retcode',None)}")
        mt5.shutdown()
    except Exception as e:
        audit_write({"ts": now_iso(),"type":"#ERROR","where":"run_agents_mt5","err":str(e)})
        print("[agents] error:", e); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
