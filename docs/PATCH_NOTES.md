# PATCH_NOTES

This patch fixes P0 issues:

1. dashboard/app.py — timeframe mapping and empty data handling, add XAUUSD selector.
2. backtest_daily_all_agents.py — correct config path, clean Telegram summary.
3. utils/telegram_client.py — add TelegramClient wrapper used by tests.
4. requirements.txt — remove duplicates, add streamlit.

No other modules were changed.
