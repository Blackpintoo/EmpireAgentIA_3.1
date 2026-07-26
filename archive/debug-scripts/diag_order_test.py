"""
Script de diagnostic COMPLET pour tester l'envoi d'ordres MT5.
Exécuter sur Windows avec MT5 connecté.
"""
import MetaTrader5 as mt5

SYMBOLS_TO_TEST = ["ADAUSD", "EURUSD", "BTCUSD", "XAUUSD", "USDJPY"]

if not mt5.initialize():
    print("Erreur MT5:", mt5.last_error())
    exit()

print("=" * 70)
print("DIAGNOSTIC COMPLET - Broker:", mt5.account_info().server)
print("Account:", mt5.account_info().login)
print("Balance:", mt5.account_info().balance)
print("=" * 70)

# Test 1: Vérifier les filling modes supportés
print("\n1. FILLING MODES PAR SYMBOLE:")
print("-" * 70)
for sym in SYMBOLS_TO_TEST:
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"  {sym}: SYMBOLE INTROUVABLE")
        continue

    filling_mode = info.filling_mode
    print(f"  {sym}: filling_mode={filling_mode} (binaire)")

    # Décoder les modes supportés
    modes = []
    if filling_mode & 1:  # ORDER_FILLING_FOK
        modes.append("FOK(0)")
    if filling_mode & 2:  # ORDER_FILLING_IOC
        modes.append("IOC(1)")
    if filling_mode & 4:  # ORDER_FILLING_RETURN (BOC)
        modes.append("RETURN(2)")
    print(f"           Modes supportés: {modes if modes else 'AUCUN!'}")

# Test 2: Tester order_check avec différents filling modes
print("\n2. TEST ORDER_CHECK PAR SYMBOLE ET FILLING MODE:")
print("-" * 70)

for sym in SYMBOLS_TO_TEST:
    info = mt5.symbol_info(sym)
    if info is None:
        continue

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        print(f"  {sym}: Pas de tick disponible")
        continue

    vol_min = info.volume_min
    digits = info.digits
    price = round(tick.ask, digits)

    print(f"\n  {sym} (vol_min={vol_min}, digits={digits}, price={price}):")

    # Tester chaque filling mode
    for fill_name, fill_value in [("FOK", mt5.ORDER_FILLING_FOK),
                                   ("IOC", mt5.ORDER_FILLING_IOC),
                                   ("RETURN", mt5.ORDER_FILLING_RETURN)]:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": vol_min,
            "type": mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": 30,
            "magic": 0,
            "comment": "diag_test",
            "type_filling": fill_value,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        result = mt5.order_check(request)
        if result is None:
            err = mt5.last_error()
            print(f"    {fill_name}: order_check=None, last_error={err}")
        else:
            status = "OK" if result.retcode == 0 else f"FAIL({result.retcode})"
            print(f"    {fill_name}: retcode={result.retcode} ({status}) comment='{result.comment}'")

# Test 3: Tester un ordre réel avec le bon filling mode (sans l'exécuter vraiment)
print("\n3. TEST AVEC MEILLEUR FILLING MODE:")
print("-" * 70)

for sym in ["EURUSD", "BTCUSD"]:
    info = mt5.symbol_info(sym)
    if info is None:
        continue

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        continue

    # Déterminer le meilleur filling mode
    filling_mode = info.filling_mode
    best_fill = None
    if filling_mode & 2:  # IOC préféré
        best_fill = mt5.ORDER_FILLING_IOC
        fill_name = "IOC"
    elif filling_mode & 4:  # RETURN
        best_fill = mt5.ORDER_FILLING_RETURN
        fill_name = "RETURN"
    elif filling_mode & 1:  # FOK
        best_fill = mt5.ORDER_FILLING_FOK
        fill_name = "FOK"
    else:
        print(f"  {sym}: Aucun filling mode supporté!")
        continue

    vol_min = info.volume_min
    digits = info.digits
    price = round(tick.ask, digits)
    sl = round(price - 100 * info.point, digits)
    tp = round(price + 100 * info.point, digits)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": vol_min,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 30,
        "magic": 0,
        "comment": "diag_test",
        "type_filling": best_fill,
        "type_time": mt5.ORDER_TIME_GTC,
    }

    print(f"\n  {sym} avec {fill_name}:")
    print(f"    Request: vol={vol_min}, price={price}, sl={sl}, tp={tp}")

    result = mt5.order_check(request)
    if result is None:
        print(f"    order_check: None - {mt5.last_error()}")
    else:
        print(f"    order_check: retcode={result.retcode} comment='{result.comment}'")
        if result.retcode == 0:
            print(f"    >>> ORDRE VALIDE - Prêt à être envoyé")

mt5.shutdown()
print("\n" + "=" * 70)
print("DIAGNOSTIC TERMINÉ")
print("=" * 70)
