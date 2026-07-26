# scripts/check_mt5_connection.py
"""
Script de diagnostic complet MT5
Exécuter depuis Windows: python scripts/check_mt5_connection.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

print("=" * 60)
print("DIAGNOSTIC COMPLET MT5 - EmpireAgentIA")
print("=" * 60)

# 1. Vérifier l'import MT5
print("\n[1] Import MetaTrader5...")
try:
    import MetaTrader5 as mt5
    print(f"    ✅ MetaTrader5 importé (version {mt5.__version__})")
except ImportError as e:
    print(f"    ❌ ERREUR: {e}")
    print("    → Installer avec: pip install MetaTrader5")
    sys.exit(1)

# 2. Charger la config (avec expansion ${VAR} depuis .env)
print("\n[2] Chargement config.yaml...")
try:
    from utils.config import load_config
    cfg = load_config()
    mt5_cfg = cfg.get("mt5", {})
    account = mt5_cfg.get("account")
    password = mt5_cfg.get("password")
    server = mt5_cfg.get("server")
    print(f"    ✅ Config chargée")
    print(f"    Account: {account}")
    print(f"    Server: {server}")
except Exception as e:
    print(f"    ❌ ERREUR: {e}")
    sys.exit(1)

# 3. Initialiser MT5
print("\n[3] Initialisation MT5...")
if not mt5.initialize():
    error = mt5.last_error()
    print(f"    ❌ ERREUR initialize: {error}")
    print("\n    Causes possibles:")
    print("    - MetaTrader 5 n'est pas lancé")
    print("    - Terminal path incorrect")
    print("    - Permissions insuffisantes")
    sys.exit(1)
print("    ✅ MT5 initialisé")

# 4. Info terminal
print("\n[4] Informations Terminal...")
terminal_info = mt5.terminal_info()
if terminal_info:
    print(f"    Path: {terminal_info.path}")
    print(f"    Data path: {terminal_info.data_path}")
    print(f"    Connected: {terminal_info.connected}")
    print(f"    Trade allowed: {terminal_info.trade_allowed}")
    print(f"    Company: {getattr(terminal_info, 'company', 'N/A')}")
    print(f"    Name: {getattr(terminal_info, 'name', 'N/A')}")
else:
    print("    ⚠️ Impossible d'obtenir les infos terminal")

# 5. Login
print("\n[5] Connexion au compte...")
if not mt5.login(account, password=password, server=server):
    error = mt5.last_error()
    print(f"    ❌ ERREUR login: {error}")
    mt5.shutdown()
    sys.exit(1)
print(f"    ✅ Connecté au compte {account}")

# 6. Info compte
print("\n[6] Informations Compte...")
account_info = mt5.account_info()
if account_info:
    print(f"    Login: {account_info.login}")
    print(f"    Server: {account_info.server}")
    print(f"    Balance: {account_info.balance:.2f} {account_info.currency}")
    print(f"    Equity: {account_info.equity:.2f} {account_info.currency}")
    print(f"    Margin: {account_info.margin:.2f}")
    print(f"    Free Margin: {account_info.margin_free:.2f}")
    print(f"    Leverage: 1:{account_info.leverage}")
    print(f"    Trade Mode: {account_info.trade_mode}")
    print(f"    Trade Allowed: {account_info.trade_allowed}")
    print(f"    Trade Expert: {account_info.trade_expert}")
else:
    print("    ❌ Impossible d'obtenir les infos compte")

# 7. Vérifier les symboles
print("\n[7] Vérification des symboles activés...")
try:
    profiles = yaml.safe_load(open("config/profiles.yaml", encoding="utf-8"))
    enabled_symbols = profiles.get("enabled_symbols", [])
except:
    enabled_symbols = ["BTCUSD", "EURUSD", "XAUUSD"]

symbols_ok = []
symbols_ko = []

for sym in enabled_symbols:
    info = mt5.symbol_info(sym)
    if info is None:
        symbols_ko.append((sym, "Non trouvé"))
    elif not info.visible:
        # Essayer de l'activer
        if mt5.symbol_select(sym, True):
            symbols_ok.append((sym, f"Activé (spread: {info.spread})"))
        else:
            symbols_ko.append((sym, "Impossible à activer"))
    else:
        tick = mt5.symbol_info_tick(sym)
        if tick:
            symbols_ok.append((sym, f"OK - Bid: {tick.bid}, Ask: {tick.ask}, Spread: {info.spread}"))
        else:
            symbols_ok.append((sym, f"OK (pas de tick)"))

print(f"\n    Symboles OK ({len(symbols_ok)}):")
for sym, status in symbols_ok:
    print(f"      ✅ {sym}: {status}")

if symbols_ko:
    print(f"\n    Symboles ERREUR ({len(symbols_ko)}):")
    for sym, status in symbols_ko:
        print(f"      ❌ {sym}: {status}")

# 8. Vérifier les positions ouvertes
print("\n[8] Positions ouvertes...")
positions = mt5.positions_get()
if positions is None or len(positions) == 0:
    print("    Aucune position ouverte")
else:
    print(f"    {len(positions)} position(s) ouverte(s):")
    for pos in positions:
        profit_color = "+" if pos.profit >= 0 else ""
        print(f"      - {pos.symbol} {['BUY','SELL'][pos.type]} {pos.volume} lots @ {pos.price_open} | P&L: {profit_color}{pos.profit:.2f}")

# 9. Vérifier les ordres en attente
print("\n[9] Ordres en attente...")
orders = mt5.orders_get()
if orders is None or len(orders) == 0:
    print("    Aucun ordre en attente")
else:
    print(f"    {len(orders)} ordre(s) en attente")

# 10. Test de trading (dry)
print("\n[10] Test capacité de trading...")
trade_allowed = getattr(account_info, 'trade_allowed', True)
trade_expert = getattr(account_info, 'trade_expert', True)
if trade_allowed:
    print("    ✅ Trading autorisé sur le compte")
else:
    print("    ⚠️ Trading bloqué sur le compte (trade_allowed = False)")

# 11. Historique récent
print("\n[11] Historique des derniers trades...")
from datetime import datetime, timedelta
now = datetime.now()
yesterday = now - timedelta(days=7)
deals = mt5.history_deals_get(yesterday, now)
if deals is None or len(deals) == 0:
    print("    Aucun trade dans les 7 derniers jours")
else:
    print(f"    {len(deals)} deal(s) dans les 7 derniers jours")
    # Afficher les 5 derniers
    for deal in deals[-5:]:
        deal_type = ["BUY", "SELL", "BALANCE", "CREDIT", "CHARGE", "CORRECTION", "BONUS", "COMMISSION", "DAILY_COMMISSION", "MONTHLY_COMMISSION", "AGENT_COMMISSION", "INTEREST"][deal.type] if deal.type < 12 else f"TYPE_{deal.type}"
        print(f"      - {deal.symbol or 'N/A'} {deal_type} {deal.volume} @ {deal.price} | P&L: {deal.profit:.2f}")

# Résumé
print("\n" + "=" * 60)
print("RÉSUMÉ")
print("=" * 60)

all_ok = True

if terminal_info and terminal_info.connected:
    print("✅ Terminal MT5 connecté")
else:
    print("❌ Terminal MT5 non connecté")
    all_ok = False

if account_info:
    print(f"✅ Compte {account_info.login} connecté ({account_info.balance:.2f} {account_info.currency})")
else:
    print("❌ Compte non connecté")
    all_ok = False

if account_info and getattr(account_info, 'trade_allowed', True):
    print("✅ Trading autorisé")
else:
    print("⚠️ Trading peut être bloqué")
    all_ok = False

print(f"✅ {len(symbols_ok)}/{len(enabled_symbols)} symboles disponibles")
if symbols_ko:
    print(f"⚠️ {len(symbols_ko)} symboles indisponibles: {', '.join([s[0] for s in symbols_ko])}")

if all_ok:
    print("\n🎉 TOUT EST OK - Le système peut trader!")
else:
    print("\n⚠️ Des problèmes ont été détectés - Vérifiez les points ci-dessus")

mt5.shutdown()
print("\n[FIN] MT5 déconnecté proprement")
