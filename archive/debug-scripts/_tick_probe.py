from utils.mt5_client import MT5Client
import MetaTrader5 as mt5

mt = MT5Client()
for s in ("LINKUSD","LNKUSD"):
    try:
        mt.ensure_symbol(s)
    except Exception as e:
        print("ensure_symbol error for", s, ":", e)
    get_tick = getattr(mt, "get_tick", None)
    tick = get_tick(s) if callable(get_tick) else None
    print(f"{s} tick:", bool(tick), tick)
