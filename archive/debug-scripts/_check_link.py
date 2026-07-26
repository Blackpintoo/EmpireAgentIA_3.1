from utils.mt5_client import MT5Client

mt = MT5Client()
mt.ensure_symbol("LINKUSD")

print("Resolved broker symbol:", MT5Client.resolve_symbol_name("LINKUSD"))
tick = mt.get_tick("LINKUSD")
print("Tick received?", bool(tick))
