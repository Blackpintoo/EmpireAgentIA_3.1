import os, yaml
p = os.path.join("config","config.yaml")
print("config path:", p, "exists:", os.path.exists(p))
cfg = yaml.safe_load(open(p, encoding="utf-8")) or {}
tg = cfg.get("telegram") or {}
print("telegram section:", tg)
print("token present:", bool(tg.get("bot_token") or tg.get("token")))
print("chat_id present:", bool(tg.get("chat_id")))
