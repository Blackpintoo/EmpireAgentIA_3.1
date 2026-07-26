import requests, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.config import load_config
cfg = load_config()
tg  = cfg.get("telegram") or {}
token = tg.get("token") or tg.get("bot_token")
api = f"https://api.telegram.org/bot{token}"
print("deleteWebhook:", requests.get(f"{api}/deleteWebhook", timeout=15).json())
print("getWebhookInfo:", requests.get(f"{api}/getWebhookInfo", timeout=15).json())
