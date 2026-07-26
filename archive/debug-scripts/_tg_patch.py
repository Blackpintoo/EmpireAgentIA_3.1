import yaml, time, shutil
p="config/config.yaml"
data = yaml.safe_load(open(p, encoding="utf-8")) or {}
tg = data.setdefault("telegram", {})
# désactive le mode "validation only"
tg["send_trade_validation_only"] = False
# s'assure que les kinds utilisés sont autorisés
kinds = set(tg.get("allow_kinds") or [])
kinds.update(["startup","status","proposal","trade_validation","news_digest"])
tg["allow_kinds"] = sorted(kinds)
bak = f"{p}.{time.strftime('%Y%m%d_%H%M%S')}.bak"
shutil.copy2(p, bak)
with open(p, "w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
print("Patched. Backup:", bak)
