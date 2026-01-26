# tg_buttons_smoke.py
import os, json, yaml, requests

CFG = os.path.join("config", "config.yaml")
tg = (yaml.safe_load(open(CFG, encoding="utf-8")) or {}).get("telegram", {}) or {}
TOKEN = tg.get("token") or tg.get("bot_token")
CHAT_ID = tg.get("chat_id")

if not (TOKEN and CHAT_ID):
    raise SystemExit("Config Telegram incomplète (token/chat_id manquants).")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
kb = {
    "inline_keyboard": [[
        {"text": "✅ Valider", "callback_data": "smoke|VALIDATE"},
        {"text": "❌ Rejeter", "callback_data": "smoke|REJECT"}
    ]]
}
payload = {
    "chat_id": CHAT_ID,
    "text": "🧪 Test boutons (smoke) — vois-tu ✅/❌ ?",
    "reply_markup": json.dumps(kb),
    "disable_web_page_preview": True,
    # "parse_mode": "Markdown"  # optionnel
}

r = requests.post(url, data=payload, timeout=10)
print("status:", r.status_code)
print("resp:", r.text[:400])
