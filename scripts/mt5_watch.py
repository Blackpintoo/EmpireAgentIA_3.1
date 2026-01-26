# scripts/mt5_watch.py
import sys, time, pathlib, traceback
from datetime import datetime, timedelta

def main():
    try:
        import MetaTrader5 as mt5
    except Exception:
        print("❌ Module MetaTrader5 introuvable. Installe-le ou lance depuis l'environnement où il est dispo.")
        return 2

    if not mt5.initialize():
        print(f"❌ MT5 initialize failed: {mt5.last_error()}")
        return 2

    print("✅ MT5 connecté (initialize). Ctrl+C pour arrêter.")
    try:
        while True:
            acc = mt5.account_info()
            now = datetime.now()
            print("\n=== SNAPSHOT", now.strftime("%Y-%m-%d %H:%M:%S"), "===")
            if acc:
                print(f"Compte: {acc.login} | Balance={acc.balance:.2f} | Equity={acc.equity:.2f} | Margin={acc.margin:.2f}")

            poss = mt5.positions_get()
            print(f"Positions ouvertes: {len(poss) if poss is not None else 0}")
            if poss:
                for p in poss:
                    print(f"  #{p.ticket} {p.symbol} {('BUY' if p.type==0 else 'SELL')} lot={p.volume} price={p.price_open} sl={p.sl} tp={p.tp} profit={p.profit:.2f}")

            orders = mt5.orders_get()
            print(f"Ordres en attente: {len(orders) if orders is not None else 0}")
            if orders:
                for o in orders:
                    print(f"  #{o.ticket} {o.symbol} type={o.type} lot={o.volume_current} price={o.price_open}")

            # derniers deals (5 dernières minutes)
            frm = now - timedelta(minutes=5)
            deals = mt5.history_deals_get(frm, now)
            if deals is not None:
                print(f"Deals 5min: {len(deals)}")
                for d in sorted(deals, key=lambda x: x.time, reverse=True)[:5]:
                    print(f"  deal #{d.ticket} {d.symbol} type={d.type} price={d.price} profit={d.profit:.2f}")
            else:
                print("Deals 5min: 0")

            sys.stdout.flush()
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nArrêt demandé par l’utilisateur.")
    except Exception:
        traceback.print_exc()
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    sys.exit(main())
