"""
PHASE 4 - Test AssetManager
Démontre l'utilisation de la configuration par type d'actif
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.asset_manager import get_asset_manager

print("=" * 80)
print("🧪 TEST ASSET MANAGER - PHASE 4")
print("=" * 80)

# Initialisation
am = get_asset_manager()

# Liste des symboles à tester
test_symbols = [
    "BTCUSD",   # CRYPTO
    "EURUSD",   # FOREX
    "US30",     # INDICE
    "XAUUSD",   # COMMODITY
]

print("\n📊 IDENTIFICATION DES TYPES D'ACTIFS")
print("-" * 80)
for symbol in test_symbols:
    asset_type = am.get_asset_type(symbol)
    print(f"{symbol:10} → {asset_type}")

# Test des sessions de trading
print("\n⏰ VÉRIFICATION DES SESSIONS DE TRADING")
print("-" * 80)
now = datetime.now(ZoneInfo("Europe/Zurich"))
print(f"Heure actuelle : {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

for symbol in test_symbols:
    allowed, reason = am.is_trading_allowed(symbol, now)
    status = "✅ AUTORISÉ" if allowed else "❌ INTERDIT"
    print(f"{symbol:10} → {status:15} | Raison: {reason}")

# Test des paramètres de risque
print("\n💰 PARAMÈTRES DE RISQUE")
print("-" * 80)
for symbol in test_symbols:
    risk_pct = am.get_risk_per_trade(symbol)
    max_loss = am.get_max_daily_loss(symbol)
    max_pos = am.get_max_parallel_positions(symbol)
    print(f"{symbol:10} → Risk: {risk_pct*100:.1f}% | Max Loss: {max_loss*100:.1f}% | Max Pos: {max_pos}")

# Test des spreads et commissions
print("\n💵 SPREADS & COMMISSIONS")
print("-" * 80)
for symbol in test_symbols:
    sc = am.get_spread_commission(symbol)
    spread = sc.get("avg_spread_points", 0)
    commission = sc.get("commission_per_lot", 0)
    print(f"{symbol:10} → Spread: {spread:3.0f} pts | Commission: ${commission:.1f}/lot")

# Test des timeframes
print("\n⏱️  TIMEFRAMES RECOMMANDÉS")
print("-" * 80)
for symbol in test_symbols:
    primary = am.get_primary_timeframe(symbol)
    tfs = am.get_timeframes(symbol)
    secondary = tfs.get("secondary", [])
    print(f"{symbol:10} → Primary: {primary:4} | Secondary: {', '.join(secondary)}")

# Test des paramètres techniques
print("\n📊 PARAMÈTRES TECHNIQUES (ATR)")
print("-" * 80)
for symbol in test_symbols:
    sl_mult, tp_mult = am.get_atr_multipliers(symbol)
    print(f"{symbol:10} → SL: {sl_mult:.1f}×ATR | TP: {tp_mult:.1f}×ATR")

# Test des corrélations
print("\n🔗 GROUPES DE CORRÉLATION")
print("-" * 80)
corr_groups = am.get_correlation_groups()
for i, group in enumerate(corr_groups, 1):
    print(f"Groupe {i}: {' ↔ '.join(group)}")

# Test des conflits de corrélation
print("\n⚠️  TEST CONFLITS DE CORRÉLATION")
print("-" * 80)
test_cases = [
    (["EURUSD"], "GBPUSD"),
    (["XAUUSD"], "XAGUSD"),
    (["US30"], "NAS100"),
    (["BTCUSD"], "EURUSD"),  # Pas de corrélation
]

for open_pos, new_symbol in test_cases:
    conflict = am.check_correlation_conflict(new_symbol, open_pos)
    status = "❌ CONFLIT" if conflict else "✅ OK"
    print(f"Positions ouvertes: {open_pos} | Nouveau: {new_symbol:10} → {status}")

# Test de l'exposition max
print("\n📈 EXPOSITION MAXIMALE PAR TYPE")
print("-" * 80)
for symbol in test_symbols:
    asset_type = am.get_asset_type(symbol)
    max_exp = am.get_max_exposure(symbol)
    print(f"{symbol:10} ({asset_type:12}) → Max: {max_exp*100:.1f}% du capital")

# Ordre de priorité
print("\n🎯 ORDRE DE PRIORITÉ DES TYPES D'ACTIFS")
print("-" * 80)
priority = am.get_priority_order()
for i, asset_type in enumerate(priority, 1):
    print(f"{i}. {asset_type}")

print("\n" + "=" * 80)
print("✅ TEST TERMINÉ")
print("=" * 80)
