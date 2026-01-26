import yaml, sys, pathlib

p = pathlib.Path("config/profiles.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8"))

errors = []

profiles = cfg.get("profiles") or {}
for sym in ["BTCUSD","ETHUSD","LINKUSD","BNBUSD","EURUSD","XAUUSD"]:
    if sym not in profiles:
        errors.append(f"[MISSING] {sym} absent de profiles:")
        continue
    sec = profiles[sym]
    inst = (sec.get("instrument") or {})
    risk = (sec.get("risk") or {})

    # Sanity instrument
    for k in ["broker_symbol","digits","point","pip_value","lot_step","lot_min","slippage"]:
        if k not in inst:
            errors.append(f"[{sym}] instrument.{k} manquant")

    # EURUSD specifics
    if sym == "EURUSD":
        if inst.get("digits") != 5 or abs(inst.get("point",0)-1e-5) > 1e-9 or inst.get("pip_value") != 10.0:
            errors.append("[EURUSD] digits/point/pip_value incorrects")

    # Risk nesting
    if "risk_per_trade" not in risk:
        errors.append(f"[{sym}] risk.risk_per_trade introuvable (indentation?)")

if errors:
    print("❌ Problèmes détectés:")
    print("\n".join("- " + e for e in errors))
    sys.exit(1)
print("✅ profiles.yaml OK")

