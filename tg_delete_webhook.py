import yaml, requests, os
cfg = yaml.safe_load(open(os.path.join("config","config.yaml"), encoding="utf-8")) or {}
tg  = cfg.get("telegram") or {}
token = tg.get("token") or tg.get("bot_token")
api = f"https://api.telegram.org/bot{token}"
print("deleteWebhook:", requests.get(f"{api}/deleteWebhook", timeout=15).json())
print("getWebhookInfo:", requests.get(f"{api}/getWebhookInfo", timeout=15).json())
