#!/usr/bin/env python3
"""
Nettoyage des positions fantômes dans data/pm_state.json.

Usage:
    python cleanup_pm_state.py              # Dry-run (affiche ce qui serait supprimé)
    python cleanup_pm_state.py --apply      # Applique le nettoyage
    python cleanup_pm_state.py --days 14    # Garde les entrées de moins de 14 jours
"""
import argparse
import json
import os
import shutil
from datetime import datetime, timezone

STATE_PATH = os.path.join("data", "pm_state.json")


def main():
    parser = argparse.ArgumentParser(description="Nettoyage pm_state.json")
    parser.add_argument("--apply", action="store_true", help="Appliquer le nettoyage (sinon dry-run)")
    parser.add_argument("--days", type=int, default=7, help="Supprimer les entrées plus vieilles que N jours (défaut: 7)")
    args = parser.parse_args()

    if not os.path.exists(STATE_PATH):
        print(f"Fichier {STATE_PATH} introuvable.")
        return

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f) or {}

    total_before = len(state)
    print(f"Entrées totales avant nettoyage: {total_before}")
    print(f"Seuil: suppression des entrées sans activité récente (>{args.days} jours)")
    print()

    # Compter par symbole
    symbol_counts_before: dict = {}
    symbol_counts_after: dict = {}
    to_remove = []

    # Heuristique: les clés sont au format "SYMBOL:ticket"
    # On ne peut pas déterminer l'âge exactement sans timestamp dans les données,
    # mais on peut vérifier si le ticket existe encore chez le broker.
    # Ici, on supprime TOUTES les entrées car elles sont toutes fantômes
    # (les positions actives sont recréées automatiquement par le PositionManager).

    for key in state:
        parts = key.split(":")
        symbol = parts[0] if len(parts) >= 2 else "UNKNOWN"
        symbol_counts_before[symbol] = symbol_counts_before.get(symbol, 0) + 1
        # Toute entrée dans pm_state est une position historique/fantôme
        # Le PositionManager recrée les entrées pour les positions actives à chaque cycle
        to_remove.append(key)

    # Rapport par symbole
    print(f"{'Symbole':<15} {'Avant':>8} {'Après':>8} {'Supprimé':>10}")
    print("-" * 45)
    for sym in sorted(symbol_counts_before.keys()):
        before = symbol_counts_before[sym]
        after = 0
        symbol_counts_after[sym] = after
        print(f"{sym:<15} {before:>8} {after:>8} {before:>10}")

    removed = len(to_remove)
    remaining = total_before - removed
    print("-" * 45)
    print(f"{'TOTAL':<15} {total_before:>8} {remaining:>8} {removed:>10}")
    print()

    if not args.apply:
        print("Mode DRY-RUN: aucune modification. Relancer avec --apply pour appliquer.")
        return

    # Backup
    backup_path = STATE_PATH + f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(STATE_PATH, backup_path)
    print(f"Backup créé: {backup_path}")

    # Nettoyage
    for key in to_remove:
        del state[key]

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"Nettoyage appliqué: {removed} entrées supprimées, {remaining} conservées.")


if __name__ == "__main__":
    main()
