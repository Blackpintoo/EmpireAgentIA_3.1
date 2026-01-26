import MetaTrader5 as mt5
from utils.mt5_client import MT5Client
mt = MT5Client()
poss = mt5.positions_get() or []
print("Open positions:", len(poss))
for p in poss:
    print(p.ticket, p.symbol, "BUY" if p.type==mt5.POSITION_TYPE_BUY else "SELL", p.volume)
