# quick_check_overrides.py
import yaml, pprint
with open("config/overrides.yaml","r",encoding="utf-8") as f:
    ov = yaml.safe_load(f)
for k in ("BTCUSD","ETHUSD","LINKUSD","BNBUSD"):
    print(">>>", k)
    assert "crypto_bucket_cap_override" in ov.get(k,{}), f"{k}: cap override manquant"
    pm = ov[k].get("position_manager", {})
    assert "enabled" in pm, f"{k}: position_manager.enabled manquant"
    assert "breakeven" in pm and "break_even" not in pm, f"{k}: garde 'breakeven' uniquement"
print("Overrides OK ✅")
