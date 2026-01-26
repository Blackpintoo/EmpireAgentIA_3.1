from utils.mt5_client import MT5Client
from utils.logger import logger

mt = MT5Client()
sym = "BTCUSD"   # ou "XAUUSD" / "EURUSD" / "LINKUSD" (LNKUSD côté broker)

try:
    mt.ensure_symbol(sym)
    tick = mt.get_tick(sym)
    print("Tick:", tick)
    res = mt.place_order(sym, "BUY", volume=0.01)  # sans SL/TP pour smoke test
    print("order_send:", res)
except Exception as e:
    logger.exception(f"Smoke test error: {e}")
