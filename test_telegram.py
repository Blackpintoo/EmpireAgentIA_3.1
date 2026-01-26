from utils.telegram_client import send_message

print("send_message (direct):", send_message("Test .env OK", kind="status", force=True))
print("send_message (second):", send_message("Test client OK", kind="status", force=True))
