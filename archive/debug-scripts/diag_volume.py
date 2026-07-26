"""
Script de diagnostic pour vérifier les contraintes de volume chez le broker.
Exécuter sur Windows avec MT5 connecté.
"""
import MetaTrader5 as mt5

SYMBOLS = ["BTCUSD", "LTCUSD", "USDJPY", "EURUSD", "XAUUSD", "GER40"]

if not mt5.initialize():
    print("Erreur MT5:", mt5.last_error())
    exit()

print("=" * 70)
print("DIAGNOSTIC VOLUME - Broker:", mt5.account_info().server)
print("=" * 70)

print(f"\n{'Symbol':<12} {'vol_min':<10} {'vol_max':<10} {'vol_step':<10} {'trade_mode':<15} {'status'}")
print("-" * 70)

for sym in SYMBOLS:
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"{sym:<12} {'N/A':<10} {'N/A':<10} {'N/A':<10} {'N/A':<15} SYMBOLE INTROUVABLE")
        # Chercher alternatives
        all_syms = [s.name for s in mt5.symbols_get()]
        alts = [s for s in all_syms if sym[:3] in s][:3]
        if alts:
            print(f"             Alternatives: {alts}")
        continue

    vol_min = info.volume_min
    vol_max = info.volume_max
    vol_step = info.volume_step
    trade_mode = info.trade_mode

    # Vérifier si le mode de trading est actif
    mode_ok = trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED
    status = "OK" if mode_ok else "TRADING DISABLED"

    print(f"{sym:<12} {vol_min:<10.3f} {vol_max:<10.1f} {vol_step:<10.3f} {trade_mode:<15} {status}")

print("\n" + "=" * 70)
print("LÉGENDE trade_mode:")
print(f"  0 = DISABLED, 1 = LONGONLY, 2 = SHORTONLY, 4 = FULL")
print("=" * 70)

# Test d'un ordre simulé (sans l'envoyer)
print("\nTEST CHECK_ORDER (validation sans envoi):")
for sym in ["BTCUSD", "USDJPY"]:
    info = mt5.symbol_info(sym)
    if info is None:
        continue
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        continue

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": info.volume_min,
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "deviation": 30,
        "magic": 0,
        "comment": "diag_test",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_check(request)
    if result is None:
        print(f"  {sym}: order_check returned None - {mt5.last_error()}")
    else:
        print(f"  {sym}: retcode={result.retcode} comment='{result.comment}'")

mt5.shutdown()
print("\nDone.")
