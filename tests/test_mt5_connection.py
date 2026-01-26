import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.mt5_client import MT5Client
import MetaTrader5 as mt5

def test_fetch_and_paper_order():
    try:
        mt5_client = MT5Client()
        print("✅ MT5 initialisé avec succès")
        
        # 1. Récupération d'OHLC
        ohlc = mt5_client.fetch_ohlc("BTCUSD", mt5.TIMEFRAME_M1, n=5)
        print("Résultat fetch OHLC (5 dernières bougies):")
        for r in ohlc:
            print(f"  time={r['time']}, open={r['open']}, close={r['close']}")

        # 2. Envoi d'un ordre paper (volume min.)
        res = mt5_client.place_order("BTCUSD", lot=0.001, order_type=mt5.ORDER_TYPE_BUY)
        if res is None:
            print("❌ La fonction place_order a retourné None (ordre non envoyé ou erreur dans la méthode).")
        elif hasattr(res, "retcode") and res.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"✅ Ordre paper passé avec succès, ticket={getattr(res, 'order', res)}")
        else:
            print(f"❌ Erreur ordre paper: code={getattr(res, 'retcode', 'N/A')}, msg={getattr(res, 'comment', 'N/A')}")
    except Exception as e:
        print(f"❌ Exception pendant le test: {e}")

if __name__ == "__main__":
    test_fetch_and_paper_order()