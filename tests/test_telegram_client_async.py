import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from utils.telegram_client_async import AsyncTelegramClient

TOKEN = "7969631468:AAHzPL6iCB9kO0K1iPtVeTkP-L2FevVdttc"
CHAT_ID = "5277012507"

async def main():
    client = AsyncTelegramClient(TOKEN, CHAT_ID)
    ok = await client.send_message("✅ Test async Telegram (aiogram) depuis EmpireAgentIA3")
    await client.close()
    print("Succès" if ok else "Échec")

if __name__ == "__main__":
    asyncio.run(main())
