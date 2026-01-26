import json, requests, yaml, os, time

cfg = yaml.safe_load(open(os.path.join("config","config.yaml"), encoding="utf-8")) or {}
tg  = cfg.get("telegram") or {}
token = tg.get("token") or tg.get("bot_token")
api = f"https://api.telegram.org/bot{token}"

def jget(url, **kw):
    r = requests.get(url, timeout=30, **kw)
    return r.status_code, r.json()

print("→ getMe:")
print(jget(f"{api}/getMe")[1])

print("→ getWebhookInfo:")
print(jget(f"{api}/getWebhookInfo")[1])

# On “vide” la file pour repartir propre
code, data = jget(f"{api}/getUpdates", params={"timeout": 1, "allowed_updates":["callback_query","message"]})
offset = None
if data.get("result"):
    offset = data["result"][-1]["update_id"] + 1

print("✅ Maintenant clique sur le bouton Telegram… (attente 20s)")
code, data = jget(f"{api}/getUpdates",
                  params={"timeout": 20, "allowed_updates":["callback_query"], "offset": offset})
print(json.dumps(data, ensure_ascii=False, indent=2))
