# scripts/test_trade.py
"""
Script de test pour ouvrir et fermer une position.
Exécuter depuis Windows: python scripts/test_trade.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
import yaml
import requests
import time

# Config
cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
token = cfg["telegram"]["token"]
chat_id = cfg["telegram"]["chat_id"]

def send_telegram(text):
    """Envoie un message Telegram"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
        print(f"[TG] {text}")
    except Exception as e:
        print(f"[TG ERROR] {e}")

def main():
    print("=" * 50)
    print("TEST OUVERTURE/FERMETURE DE POSITION")
    print("=" * 50)

    # Initialiser MT5
    print("\n[1] Initialisation MT5...")
    if not mt5.initialize():
        print(f"❌ MT5 initialize failed: {mt5.last_error()}")
        return False

    # Login
    account = cfg["mt5"]["account"]
    password = cfg["mt5"]["password"]
    server = cfg["mt5"]["server"]

    print(f"[2] Connexion au compte {account}...")
    if not mt5.login(account, password=password, server=server):
        print(f"❌ MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False

    # Info compte
    info = mt5.account_info()
    print(f"✅ Connecté - Balance: {info.balance:.2f}, Equity: {info.equity:.2f}")

    # Symbole de test - Crypto (disponible 24/7, même le week-end)
    symbol = "BTCUSD"
    print(f"\n[3] Préparation du symbole {symbol}...")

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Symbole {symbol} non trouvé")
        mt5.shutdown()
        return False

    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)
        time.sleep(0.5)

    # Volume minimum
    lot = symbol_info.volume_min
    print(f"   Volume min: {lot}")

    # Prix actuel
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Impossible d'obtenir le tick pour {symbol}")
        mt5.shutdown()
        return False

    print(f"   Prix - Bid: {tick.bid}, Ask: {tick.ask}")

    # ============================================
    # OUVERTURE DE POSITION (BUY)
    # ============================================
    print(f"\n[4] OUVERTURE position BUY {lot} lot sur {symbol}...")

    request_open = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "deviation": 20,
        "magic": 999999,  # Magic number de test
        "comment": "TEST_EMPIRE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result_open = mt5.order_send(request_open)

    if result_open is None:
        print(f"❌ order_send retourné None: {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"   Retcode: {result_open.retcode}")

    if result_open.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Échec ouverture: {result_open.retcode} - {result_open.comment}")
        mt5.shutdown()
        return False

    order_id = result_open.order
    deal_id = result_open.deal
    print(f"✅ Position ouverte! Order: {order_id}, Deal: {deal_id}")

    # Notification Telegram
    send_telegram(f"🧪 TEST - Position OUVERTE\n\n"
                  f"Symbole: {symbol}\n"
                  f"Direction: BUY\n"
                  f"Volume: {lot}\n"
                  f"Prix: {tick.ask}\n"
                  f"Order ID: {order_id}")

    # Attendre un peu
    print("\n[5] Attente de 3 secondes...")
    time.sleep(3)

    # ============================================
    # FERMETURE DE POSITION (SELL)
    # ============================================
    print(f"\n[6] FERMETURE de la position...")

    # Trouver la position ouverte
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        print("⚠️ Aucune position trouvée (peut-être déjà fermée?)")
        mt5.shutdown()
        return True

    # Prendre la position avec notre magic number ou la dernière
    pos = None
    for p in positions:
        if p.magic == 999999:
            pos = p
            break
    if pos is None:
        pos = positions[-1]  # Dernière position

    print(f"   Position trouvée: Ticket {pos.ticket}, Volume {pos.volume}")

    # Nouveau tick pour le prix de fermeture
    tick = mt5.symbol_info_tick(symbol)

    request_close = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos.volume,
        "type": mt5.ORDER_TYPE_SELL,  # Inverse de BUY
        "position": pos.ticket,
        "price": tick.bid,
        "deviation": 20,
        "magic": 999999,
        "comment": "TEST_EMPIRE_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result_close = mt5.order_send(request_close)

    if result_close is None:
        print(f"❌ order_send retourné None: {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"   Retcode: {result_close.retcode}")

    if result_close.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Échec fermeture: {result_close.retcode} - {result_close.comment}")
        mt5.shutdown()
        return False

    # Calcul P&L approximatif
    pnl = (tick.bid - pos.price_open) * lot  # Pour crypto

    print(f"✅ Position fermée!")

    # Notification Telegram
    send_telegram(f"🧪 TEST - Position FERMÉE\n\n"
                  f"Symbole: {symbol}\n"
                  f"Direction: SELL (fermeture)\n"
                  f"Volume: {pos.volume}\n"
                  f"Prix ouverture: {pos.price_open}\n"
                  f"Prix fermeture: {tick.bid}\n"
                  f"P&L estimé: {pnl:.2f}")

    # Résumé final
    print("\n" + "=" * 50)
    print("✅ TEST RÉUSSI!")
    print("=" * 50)
    send_telegram("✅ TEST COMPLET RÉUSSI\n\nLe système peut ouvrir et fermer des positions correctement.")

    mt5.shutdown()
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
