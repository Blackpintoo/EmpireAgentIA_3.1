import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.telegram_client import TelegramClient
import asyncio

async def main():
    client = TelegramClient()
    await client.send_message("🚀 Test automatisé depuis EmpireAgentIA3 !")

if __name__ == "__main__":
    asyncio.run(main())
