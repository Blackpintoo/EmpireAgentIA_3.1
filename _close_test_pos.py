import MetaTrader5 as mt5
from utils.mt5_client import MT5Client

mt = MT5Client()
sym = "BTCUSD"  # change si besoin
pos = mt5.positions_get(symbol=sym) or []
if not pos:
    print("Aucune position ouverte.")
else:
    p = pos[0]
    opp = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(sym)
    price = tick.bid if opp == mt5.ORDER_TYPE_SELL else tick.ask
    fillings = [getattr(mt5,"ORDER_FILLING_RETURN",None),
                getattr(mt5,"ORDER_FILLING_IOC",None),
                getattr(mt5,"ORDER_FILLING_FOK",None)]
    for f in [m for m in fillings if m is not None]:
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "type": opp,
               "position": p.ticket, "volume": p.volume, "price": price,
               "deviation": 20, "type_filling": f}
        r = mt5.order_send(req)
        print("try fill", f, "=>", getattr(r,"retcode",None), getattr(r,"comment",""))
        if r and r.retcode == getattr(mt5,"TRADE_RETCODE_DONE",10009):
            break
