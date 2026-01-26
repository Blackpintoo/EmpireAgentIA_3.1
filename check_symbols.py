import MetaTrader5 as mt5

TARGET = ["BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "EURUSD", "XAUUSD",
          "GBPUSD", "USDJPY", "AUDUSD", "DJ30", "NAS100", "GER40",
          "XAGUSD", "CL-OIL", "ADAUSD", "SOLUSD"]

if not mt5.initialize():
    print("Erreur MT5:", mt5.last_error())
    exit()

print("Connecte a:", mt5.account_info().server)
print("Compte:", mt5.account_info().login)
print("-" * 50)

all_symbols = [s.name for s in mt5.symbols_get()]
print("Total symboles disponibles:", len(all_symbols))
print("-" * 50)

print("\nVERIFICATION DES 16 SYMBOLES:")
for sym in TARGET:
    if sym in all_symbols:
        info = mt5.symbol_info(sym)
        print(f"  OK: {sym} (spread: {info.spread})")
    else:
        print(f"  MANQUANT: {sym}")
        similar = [s for s in all_symbols if sym[:3] in s][:5]
        if similar:
            print(f"      Alternatives: {similar}")

print("\n" + "=" * 50)
print("TOUS LES SYMBOLES PAR CATEGORIE:")
print("=" * 50)

cryptos = [s for s in all_symbols if any(c in s for c in ['BTC', 'ETH', 'ADA', 'SOL', 'BNB', 'LINK', 'LTC', 'XRP', 'DOT', 'DOGE'])]
print("\nCRYPTOS:", cryptos)

indices = [s for s in all_symbols if any(i in s for i in ['US30', 'DJ30', 'DOW', 'NAS', 'NDX', 'SPX', 'GER', 'DAX', 'UK100', 'JP225'])]
print("\nINDICES:", indices)

commodities = [s for s in all_symbols if any(c in s for c in ['XAU', 'XAG', 'GOLD', 'SILVER', 'OIL', 'WTI', 'XTI'])]
print("\nMATIERES PREMIERES:", commodities)

forex = [s for s in all_symbols if s in ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCHF', 'USDCAD', 'NZDUSD']]
print("\nFOREX MAJEURS:", forex)

mt5.shutdown()