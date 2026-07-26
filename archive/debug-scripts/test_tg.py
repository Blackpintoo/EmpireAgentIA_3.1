from utils.telegram_client import send_message

btns = [
    {"text": "Valider", "callback_data": "orch|BTCUSD|VALIDATE|LONG"},
    {"text": "Rejeter", "callback_data": "orch|BTCUSD|REJECT|LONG"},
]

print("OK" if send_message("Test boutons", kind="trade_validation", force=True, buttons=btns) else "FAIL")
