#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUDIT COMPLET DES TRADES - 13-24 DECEMBRE 2025
Analyse des performances du systeme EmpireAgentIA_3
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
import json

# Configuration
DATA_DIR = Path(__file__).parent.parent / "data"
JOURNAL_DIR = DATA_DIR / "journal"

# Periode d'analyse
START_DATE = "2025-12-13"
END_DATE = "2025-12-24"

def load_trades():
    """Charge tous les trades de la periode"""
    all_trades = []

    for csv_file in sorted(JOURNAL_DIR.glob("trades_2025-12-*.csv")):
        date_str = csv_file.stem.replace("trades_", "")
        if START_DATE <= date_str <= END_DATE:
            try:
                df = pd.read_csv(csv_file)
                if not df.empty:
                    all_trades.append(df)
                    print(f"  [OK] {csv_file.name}: {len(df)} trades")
            except Exception as e:
                print(f"  [ERR] {csv_file.name}: {e}")

    if not all_trades:
        return pd.DataFrame()

    combined = pd.concat(all_trades, ignore_index=True)
    combined['timestamp'] = pd.to_datetime(combined['timestamp'])
    return combined

def analyze_trades(df):
    """Analyse statistique complete"""
    print("\n" + "="*70)
    print("STATISTIQUES GLOBALES - Periode 13-24 Decembre 2025")
    print("="*70)

    total = len(df)
    print(f"\n[VOLUME DE TRADES]")
    print(f"   Total propositions: {total}")

    # Analyser par symbole
    print(f"\n[PAR SYMBOLE]")
    symbol_stats = df.groupby('symbol').agg({
        'score': ['count', 'mean'],
        'confluence': 'mean',
        'rr_estimate': 'mean',
        'weighted_vote': 'mean'
    }).round(2)
    symbol_stats.columns = ['Count', 'Avg Score', 'Avg Confluence', 'Avg RR', 'Avg Vote']
    symbol_stats = symbol_stats.sort_values('Count', ascending=False)
    print(symbol_stats.to_string())

    # Analyser par direction
    print(f"\n[PAR DIRECTION]")
    side_stats = df.groupby('side').agg({
        'score': ['count', 'mean'],
        'confluence': 'mean'
    })
    side_stats.columns = ['Count', 'Avg Score', 'Avg Confluence']
    print(side_stats.to_string())

    # Analyser par heure
    df['hour'] = df['timestamp'].dt.hour
    print(f"\n[PAR HEURE (UTC)]")
    hour_stats = df.groupby('hour').size().sort_index()
    print("   Heure | Trades")
    for hour, count in hour_stats.items():
        bar = "#" * (count // 2)
        print(f"   {hour:02d}:00 | {count:3d} {bar}")

    # Qualite des signaux
    print(f"\n[QUALITE DES SIGNAUX]")
    high_quality = df[df['score'] >= 8.0]
    medium_quality = df[(df['score'] >= 5.0) & (df['score'] < 8.0)]
    low_quality = df[df['score'] < 5.0]

    print(f"   Score >= 8.0 (Haute qualite): {len(high_quality)} ({100*len(high_quality)/total:.1f}%)")
    print(f"   Score 5.0-8.0 (Moyenne):      {len(medium_quality)} ({100*len(medium_quality)/total:.1f}%)")
    print(f"   Score < 5.0 (Basse qualite):  {len(low_quality)} ({100*len(low_quality)/total:.1f}%)")

    # Confluence
    print(f"\n[CONFLUENCE]")
    high_conf = df[df['confluence'] >= 5]
    print(f"   Confluence >= 5: {len(high_conf)} ({100*len(high_conf)/total:.1f}%)")
    print(f"   Confluence moyenne: {df['confluence'].mean():.2f}")

    # Tracker vote (sentiment)
    print(f"\n[TRACKER VOTE - Sentiment]")
    positive_vote = df[df['tracker_vote'] > 0]
    negative_vote = df[df['tracker_vote'] < 0]
    print(f"   Vote positif: {len(positive_vote)} ({100*len(positive_vote)/total:.1f}%)")
    print(f"   Vote negatif: {len(negative_vote)} ({100*len(negative_vote)/total:.1f}%)")
    print(f"   Vote moyen: {df['tracker_vote'].mean():.4f}")

    return symbol_stats

def analyze_problematic_patterns(df):
    """Identifie les patterns problematiques"""
    print("\n" + "="*70)
    print("ANALYSE DES PATTERNS PROBLEMATIQUES")
    print("="*70)

    # Heures toxiques (faible liquidite)
    toxic_hours = [0, 1, 2, 3, 4, 5, 18, 19, 20, 21, 22, 23]
    df['hour'] = df['timestamp'].dt.hour
    toxic_trades = df[df['hour'].isin(toxic_hours)]

    print(f"\n[!] TRADES EN HEURES TOXIQUES ({toxic_hours})")
    print(f"   Total: {len(toxic_trades)} / {len(df)} ({100*len(toxic_trades)/len(df):.1f}%)")
    if not toxic_trades.empty:
        toxic_by_symbol = toxic_trades.groupby('symbol').size().sort_values(ascending=False)
        print("   Par symbole:")
        for sym, count in toxic_by_symbol.head(5).items():
            print(f"     - {sym}: {count}")

    # Low score trades
    print(f"\n[!] TRADES A FAIBLE SCORE (< 7.0)")
    low_score = df[df['score'] < 7.0]
    print(f"   Total: {len(low_score)} ({100*len(low_score)/len(df):.1f}%)")

    # Low confluence
    print(f"\n[!] TRADES A FAIBLE CONFLUENCE (< 5)")
    low_conf = df[df['confluence'] < 5]
    print(f"   Total: {len(low_conf)} ({100*len(low_conf)/len(df):.1f}%)")

    # Negative tracker vote
    print(f"\n[!] TRADES CONTRE LE TREND (tracker_vote < 0)")
    against_trend = df[df['tracker_vote'] < 0]
    print(f"   Total: {len(against_trend)} ({100*len(against_trend)/len(df):.1f}%)")
    if not against_trend.empty:
        against_by_symbol = against_trend.groupby('symbol').size().sort_values(ascending=False)
        print("   Par symbole:")
        for sym, count in against_by_symbol.head(5).items():
            print(f"     - {sym}: {count}")

    # Symboles problematiques identifies precedemment
    print(f"\n[!!!] SYMBOLES PROBLEMATIQUES IDENTIFIES")
    problem_symbols = ['ADAUSD', 'USDJPY', 'UK100', 'XAGUSD']
    for sym in problem_symbols:
        sym_trades = df[df['symbol'] == sym]
        if not sym_trades.empty:
            neg_votes = sym_trades[sym_trades['tracker_vote'] < 0]
            print(f"   {sym}: {len(sym_trades)} trades, {len(neg_votes)} contre-trend ({100*len(neg_votes)/len(sym_trades):.0f}%)")

def analyze_by_session(df):
    """Analyse par session de trading"""
    print("\n" + "="*70)
    print("ANALYSE PAR SESSION")
    print("="*70)

    df['hour'] = df['timestamp'].dt.hour

    sessions = {
        'Asian (00-06)': (0, 6),
        'London (07-10)': (7, 10),
        'NY (12-15)': (12, 15),
        'London Close (15-17)': (15, 17),
        'Off-hours (autres)': None
    }

    print(f"\n[DISTRIBUTION PAR SESSION]")
    for session_name, hours in sessions.items():
        if hours:
            start, end = hours
            session_trades = df[(df['hour'] >= start) & (df['hour'] < end)]
        else:
            # Off-hours = tout ce qui n'est pas dans les autres sessions
            other_hours = [h for h in range(24) if not any(
                s <= h < e for s, e in [(0, 6), (7, 10), (12, 15), (15, 17)]
            )]
            session_trades = df[df['hour'].isin(other_hours)]

        if len(session_trades) > 0:
            avg_score = session_trades['score'].mean()
            avg_conf = session_trades['confluence'].mean()
            neg_votes = (session_trades['tracker_vote'] < 0).sum()
            print(f"   {session_name}:")
            print(f"     Trades: {len(session_trades)}, Score moy: {avg_score:.1f}, Conf moy: {avg_conf:.1f}, Contre-trend: {neg_votes}")

def generate_recommendations(df):
    """Genere des recommandations basees sur l'analyse"""
    print("\n" + "="*70)
    print("RECOMMANDATIONS")
    print("="*70)

    recommendations = []

    # 1. Filtrage par score minimum
    low_score = df[df['score'] < 7.0]
    if len(low_score) / len(df) > 0.2:
        recommendations.append({
            'priority': 'HAUTE',
            'issue': f"{100*len(low_score)/len(df):.0f}% des trades ont un score < 7.0",
            'action': 'Augmenter HARD_MIN_SCORE a 7.0 minimum'
        })

    # 2. Filtrage par confluence
    low_conf = df[df['confluence'] < 5]
    if len(low_conf) / len(df) > 0.2:
        recommendations.append({
            'priority': 'HAUTE',
            'issue': f"{100*len(low_conf)/len(df):.0f}% des trades ont confluence < 5",
            'action': 'Augmenter HARD_MIN_CONFLUENCE a 5 minimum'
        })

    # 3. Heures toxiques
    toxic_hours = [0, 1, 2, 3, 4, 5, 18, 19, 20, 21, 22, 23]
    df['hour'] = df['timestamp'].dt.hour
    toxic = df[df['hour'].isin(toxic_hours)]
    if len(toxic) / len(df) > 0.15:
        recommendations.append({
            'priority': 'HAUTE',
            'issue': f"{100*len(toxic)/len(df):.0f}% des trades en heures toxiques",
            'action': f'Bloquer les heures: {toxic_hours}'
        })

    # 4. Trades contre-trend
    against = df[df['tracker_vote'] < 0]
    if len(against) / len(df) > 0.3:
        recommendations.append({
            'priority': 'MOYENNE',
            'issue': f"{100*len(against)/len(df):.0f}% des trades contre le trend",
            'action': 'Verifier le filtre MTF et inter-market guard'
        })

    # 5. Symboles problematiques
    problem_symbols = ['ADAUSD', 'USDJPY', 'UK100', 'XAGUSD']
    for sym in problem_symbols:
        sym_trades = df[df['symbol'] == sym]
        if len(sym_trades) > 5:
            neg = sym_trades[sym_trades['tracker_vote'] < 0]
            if len(neg) / len(sym_trades) > 0.4:
                recommendations.append({
                    'priority': 'HAUTE',
                    'issue': f"{sym}: {100*len(neg)/len(sym_trades):.0f}% trades contre-trend",
                    'action': f'Desactiver {sym} ou reviser les parametres'
                })

    print(f"\n[{len(recommendations)} RECOMMANDATIONS]")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n   [{rec['priority']}] {i}. {rec['issue']}")
        print(f"      -> Action: {rec['action']}")

    return recommendations

def main():
    print("="*70)
    print("AUDIT COMPLET - EmpireAgentIA_3")
    print(f"Periode: {START_DATE} au {END_DATE}")
    print("="*70)

    print("\n[Chargement des donnees...]")
    df = load_trades()

    if df.empty:
        print("[ERREUR] Aucun trade trouve pour la periode!")
        return

    print(f"\n[OK] {len(df)} trades charges")

    # Analyses
    analyze_trades(df)
    analyze_problematic_patterns(df)
    analyze_by_session(df)
    recommendations = generate_recommendations(df)

    # Resume final
    print("\n" + "="*70)
    print("RESUME EXECUTIF")
    print("="*70)

    total = len(df)
    high_quality = len(df[df['score'] >= 8.0])
    good_confluence = len(df[df['confluence'] >= 5])
    aligned = len(df[df['tracker_vote'] > 0])

    print(f"""
    METRIQUES CLES:
    -------------------------------------------
    Total trades analyses:     {total}
    Haute qualite (score>=8):  {high_quality} ({100*high_quality/total:.1f}%)
    Bonne confluence (>=5):    {good_confluence} ({100*good_confluence/total:.1f}%)
    Alignes au trend:          {aligned} ({100*aligned/total:.1f}%)

    OBJECTIF 5'000 CHF/MOIS:
    -------------------------------------------
    Avec un capital de 100'000 USD:
    - Rendement requis: 5.0%/mois
    - Risk per trade: 1% = 1'000 USD
    - Win rate cible: 45%+ avec RR 1:1.5
    - Trades/jour: 2-3 de haute qualite

    RECOMMANDATIONS PRIORITAIRES:
    -------------------------------------------
    """)

    for i, rec in enumerate(recommendations[:5], 1):
        print(f"    {i}. [{rec['priority']}] {rec['action']}")

    print("\n" + "="*70)

if __name__ == "__main__":
    main()
