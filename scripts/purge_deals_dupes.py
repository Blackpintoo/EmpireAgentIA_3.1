#!/usr/bin/env python3
# scripts/purge_deals_dupes.py
# FIX 2026-02-23: Purge des doublons dans deals_history.csv (Directive 1)
"""
1. Backup horodaté du fichier actuel
2. Lecture + déduplication (ordre d'apparition préservé)
3. Réécriture avec header CSV
4. Statistiques avant/après
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data", "deals_history.csv")
HEADER = "time,symbol,type,entry,volume,price,profit,commission,swap,magic,comment,position_id,order"


def main():
    if not os.path.exists(CSV_PATH):
        print(f"[ERREUR] Fichier introuvable: {CSV_PATH}")
        return 1

    # --- 1. Backup horodaté ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{CSV_PATH}.backup.{ts}"
    shutil.copy2(CSV_PATH, backup_path)
    print(f"[BACKUP] {backup_path}")

    # --- 2. Lecture + déduplication ---
    total_lines = 0
    unique_lines = []
    seen = set()

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue  # ignorer lignes vides
            if line.startswith("time,"):
                continue  # ignorer header existant
            total_lines += 1
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)

    # --- 3. Réécriture avec header ---
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(HEADER + "\n")
        for line in unique_lines:
            f.write(line + "\n")

    # --- 4. Statistiques ---
    size_before = os.path.getsize(backup_path)
    size_after = os.path.getsize(CSV_PATH)
    print(f"[STATS] Lignes avant:  {total_lines:>10,}")
    print(f"[STATS] Lignes après:  {len(unique_lines):>10,}")
    print(f"[STATS] Doublons:      {total_lines - len(unique_lines):>10,}")
    print(f"[STATS] Taille avant:  {size_before / 1024:.1f} KB")
    print(f"[STATS] Taille après:  {size_after / 1024:.1f} KB")
    print(f"[STATS] Réduction:     {(1 - size_after / max(size_before, 1)) * 100:.1f}%")
    print("[OK] Purge terminée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
