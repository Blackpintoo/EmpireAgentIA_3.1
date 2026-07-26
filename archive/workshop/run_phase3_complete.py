"""
PHASE 3 - Script Master : Optimisation + Backtests complets
Execute l'optimisation puis les backtests 2 ans sur tous les symboles
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

print("=" * 80)
print("🚀 PHASE 3 - OPTIMISATIONS ET BACKTESTS COMPLETS")
print("=" * 80)
print(f"📅 Démarrage : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# Étape 1 : Optimisation Optuna
print("\n" + "=" * 80)
print("🔧 ÉTAPE 1/2 : OPTIMISATION OPTUNA")
print("=" * 80)
print("⏱️ Durée estimée : 2-4 heures (selon N_TRIALS)")
print("🎯 Objectif : Trouver les meilleurs paramètres pour chaque agent")
print("-" * 80)

try:
    result = subprocess.run(
        [sys.executable, "optimize_all_agents_symbols.py"],
        check=True,
        capture_output=False,
        text=True
    )
    print("\n✅ Optimisation terminée avec succès !")
except subprocess.CalledProcessError as e:
    print(f"\n❌ Erreur lors de l'optimisation : {e}")
    print("⚠️ Voulez-vous continuer avec les paramètres actuels ? (y/n)")
    response = input().strip().lower()
    if response != 'y':
        print("❌ Arrêt du script")
        sys.exit(1)

# Étape 2 : Backtests complets 2 ans
print("\n" + "=" * 80)
print("📊 ÉTAPE 2/2 : BACKTESTS 2 ANS SUR 16 SYMBOLES")
print("=" * 80)
print("⏱️ Durée estimée : 1-2 heures")
print("🎯 Objectif : Valider les paramètres optimisés sur 2 ans")
print("-" * 80)

try:
    result = subprocess.run(
        [sys.executable, "backtest_all_symbols_2years.py"],
        check=True,
        capture_output=False,
        text=True
    )
    print("\n✅ Backtests terminés avec succès !")
except subprocess.CalledProcessError as e:
    print(f"\n❌ Erreur lors des backtests : {e}")
    sys.exit(1)

# Résumé final
print("\n" + "=" * 80)
print("🎉 PHASE 3 TERMINÉE AVEC SUCCÈS !")
print("=" * 80)
print(f"📅 Fin : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("\n📂 Fichiers générés :")
print("  - data/optimization_results_*.json (résultats Optuna)")
print("  - data/backtest_all_symbols_2years_*.json (résultats backtests)")
print("  - config/config.yaml (mis à jour avec meilleurs paramètres)")
print("\n💡 Prochaines étapes :")
print("  - Analyser les résultats dans data/")
print("  - Vérifier les paramètres dans config/config.yaml")
print("  - Passer à la PHASE 4 : Configuration par type d'actif")
print("=" * 80)
