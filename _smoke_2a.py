from utils.mt5_client import MT5Client
import MetaTrader5 as mt5

m = MT5Client()
sym = "LINKUSD"  # sera mappé vers LNKUSD
m.ensure_symbol(sym)

broker = m._broker_symbol(sym)
t = mt5.symbol_info_tick(broker)
print("broker symbol:", broker, "tick?", bool(t), t)

if t:
    entry = float(t.ask or t.bid or 0)
    res = m.place_order(sym, "BUY", 0.01, sl=entry-1e-6, tp=entry+1e-6)
    print("order_send:", res)
