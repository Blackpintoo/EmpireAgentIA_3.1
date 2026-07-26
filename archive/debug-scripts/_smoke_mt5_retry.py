from utils.mt5_client import MT5Client
import MetaTrader5 as mt5

mt = MT5Client()
sym = "BTCUSD"  # ou un autre

mt.ensure_symbol(sym)
info = mt5.symbol_info(sym)
print("Symbol:", sym)
print("volume_min/step/max:",
      getattr(info, "volume_min", None),
      getattr(info, "volume_step", None),
      getattr(info, "volume_max", None))
print("filling_mode (broker):", getattr(info, "filling_mode", None))

# volume minimal correct selon broker
vol = getattr(info, "volume_min", 0.01) or 0.01

res = mt.place_order(sym, "BUY", volume=vol)  # sans SL/TP pour le test rapide
print("order_send:", res)
