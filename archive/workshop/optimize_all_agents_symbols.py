"""
PHASE 3 - Optimisation Optuna pour tous les agents et symboles
Optimise les paramètres de chaque agent sur les meilleurs symboles
"""
import yaml
import json
import optuna
from pathlib import Path
from datetime import datetime, timedelta
from optimization.optimizer import optimize_agent
from utils.telegram_client import send_telegram_message

# Configuration
CONFIG_PATH = "config/config.yaml"
with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

# Symboles principaux pour optimisation (les plus liquides/populaires)
SYMBOLS_TO_OPTIMIZE = {
    "CRYPTOS": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "FOREX": ["EURUSD", "GBPUSD", "USDJPY"],
    "INDICES": ["US30", "NAS100"],
    "COMMODITIES": ["XAUUSD", "USOIL"],
}

# Agents actifs
AGENTS = ["scalping", "swing", "technical", "structure", "smart_money"]

# Paramètres Optuna
N_TRIALS = cfg.get("optuna", {}).get("n_trials", 50)
MONTHS = 12  # 1 an pour l'optimisation

print("=" * 80)
print("🔧 PHASE 3 - OPTIMISATION OPTUNA")
print("=" * 80)
print(f"🤖 Agents : {len(AGENTS)}")
print(f"📊 Symboles : {sum(len(v) for v in SYMBOLS_TO_OPTIMIZE.values())}")
print(f"🎯 Trials par agent : {N_TRIALS}")
print(f"📅 Période : {MONTHS} mois")
print("=" * 80)

results_optimization = {}
total_optimizations = 0
successful_optimizations = 0

# Optimisation par agent
for agent_key in AGENTS:
    print(f"\n🔧 Optimizing {agent_key.upper()}...")
    results_optimization[agent_key] = {}

    # Choisir les meilleurs symboles par type
    for asset_type, symbols in SYMBOLS_TO_OPTIMIZE.items():
        for symbol in symbols:
            total_optimizations += 1
            print(f"\n  📊 {symbol} ({asset_type})...")

            try:
                best_params = optimize_agent(
                    agent_key=agent_key,
                    symbol=symbol,
                    months=MONTHS,
                    n_trials=N_TRIALS
                )

                results_optimization[agent_key][symbol] = {
                    "status": "success",
                    "best_params": best_params,
                    "asset_type": asset_type,
                }

                successful_optimizations += 1
                print(f"  ✅ Optimized | Params: {len(best_params)} | {list(best_params.keys())}")

            except Exception as e:
                results_optimization[agent_key][symbol] = {
                    "status": "failed",
                    "error": str(e),
                    "asset_type": asset_type,
                }
                print(f"  ❌ Failed: {str(e)[:60]}")

# Sauvegarde des résultats
output_file = f"data/optimization_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
Path("data").mkdir(exist_ok=True)
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({
        "metadata": {
            "n_trials": N_TRIALS,
            "months": MONTHS,
            "agents": AGENTS,
            "symbols": SYMBOLS_TO_OPTIMIZE,
        },
        "summary": {
            "total": total_optimizations,
            "successful": successful_optimizations,
            "failed": total_optimizations - successful_optimizations,
        },
        "results": results_optimization,
    }, f, indent=2, default=str, ensure_ascii=False)

print("\n" + "=" * 80)
print("📊 RÉSUMÉ OPTIMISATION")
print("=" * 80)
print(f"✅ Optimisations réussies : {successful_optimizations}/{total_optimizations}")
print(f"❌ Optimisations échouées : {total_optimizations - successful_optimizations}")
print(f"💾 Résultats sauvegardés : {output_file}")
print(f"⚙️ Config mise à jour : {CONFIG_PATH}")
print("=" * 80)

# Notification Telegram
msg = [
    "🔧 PHASE 3 - Optimisation Optuna terminée",
    f"✅ {successful_optimizations}/{total_optimizations} optimisations réussies",
    f"🎯 {N_TRIALS} trials par agent",
    f"📊 {len(AGENTS)} agents optimisés",
    "⚙️ config.yaml mis à jour avec meilleurs paramètres",
]

try:
    send_telegram_message(text="\n".join(msg), kind="status")
    print("✅ Notification Telegram envoyée !")
except Exception as e:
    print(f"⚠️ Erreur notification Telegram : {e}")

print("\n💡 Prochaine étape : Exécuter backtest_all_symbols_2years.py pour valider les nouveaux paramètres")
