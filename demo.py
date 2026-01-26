"""
Script de démonstration du système de trading EmpireAgentIA 3.1
Ce script montre toutes les fonctionnalités du système
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.chart_analyzer import ChartAnalyzer
from src.learning_system import LearningSystem
from src.risk_manager import RiskManager
from src.trading_engine import TradingEngine
from src.market_data import MarketDataFetcher
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def demo_chart_analyzer():
    """Démontre l'analyse de graphiques"""
    print("\n" + "="*80)
    print("DÉMONSTRATION: Analyseur de Graphiques")
    print("="*80)
    
    # Créer des données de test
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    prices = 100 + np.cumsum(np.random.randn(100) * 2)
    
    df = pd.DataFrame({
        'open': prices + np.random.randn(100) * 0.5,
        'high': prices + np.abs(np.random.randn(100)),
        'low': prices - np.abs(np.random.randn(100)),
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)
    
    analyzer = ChartAnalyzer()
    
    # Calculer les indicateurs
    df_with_indicators = analyzer.calculate_indicators(df)
    
    print("\nIndicateurs calculés:")
    print(df_with_indicators[['close', 'SMA_20', 'RSI', 'MACD', 'Trend']].tail())
    
    # Analyser les signaux
    signals = analyzer.analyze_signals(df_with_indicators)
    
    print(f"\nSignal de trading: {signals['signal']}")
    print(f"Force du signal: {signals['strength']}")
    print(f"Raisons: {', '.join(signals['reasons']) if signals['reasons'] else 'Aucune'}")
    print(f"Indicateurs actuels: {signals['indicators']}")
    
    # Support et résistance
    support, resistance = analyzer.calculate_support_resistance(df_with_indicators)
    print(f"\nSupport: {support:.2f}")
    print(f"Résistance: {resistance:.2f}")


def demo_learning_system():
    """Démontre le système d'apprentissage"""
    print("\n" + "="*80)
    print("DÉMONSTRATION: Système d'Apprentissage")
    print("="*80)
    
    # Utiliser un fichier temporaire pour la démo
    learning = LearningSystem(history_file='demo_trade_history.json')
    
    print("\nSimulation de 20 trades...")
    
    # Simuler des trades
    for i in range(20):
        # Générer des indicateurs aléatoires
        indicators = {
            'RSI': np.random.uniform(30, 70),
            'MACD': np.random.uniform(-5, 5),
            'Trend': np.random.choice([-1, 0, 1]),
            'close': np.random.uniform(40000, 50000)
        }
        
        # Simuler un trade avec probabilité de succès basée sur les indicateurs
        profit = np.random.uniform(-100, 200) if indicators['RSI'] > 40 else np.random.uniform(-200, 50)
        
        trade_data = {
            'action': 'BUY' if i % 2 == 0 else 'SELL',
            'entry_price': indicators['close'],
            'exit_price': indicators['close'] + profit / 10,
            'profit': profit,
            'profit_percentage': (profit / indicators['close']) * 100,
            'success': profit > 0,
            'indicators': indicators,
            'reasons': ['Test signal'],
            'timestamp': (datetime.now() - timedelta(days=20-i)).isoformat()
        }
        
        learning.record_trade(trade_data)
    
    # Obtenir le rapport de performance
    report = learning.get_performance_report()
    
    print(f"\n📊 Rapport de Performance:")
    print(f"  Total trades: {report['total_trades']}")
    print(f"  Trades réussis: {report['successful_trades']}")
    print(f"  Trades ratés: {report['failed_trades']}")
    print(f"  Taux de réussite: {report['win_rate']:.1%}")
    print(f"  Profit total: {report['total_profit']:.2f}")
    print(f"  Profit moyen: {report['average_profit']:.2f}")
    print(f"  Meilleur trade: {report['best_trade']:.2f}")
    print(f"  Pire trade: {report['worst_trade']:.2f}")
    
    # Entraîner le modèle
    print("\n🤖 Entraînement du modèle d'apprentissage...")
    if learning.train_model():
        print("✅ Modèle entraîné avec succès")
        
        # Tester une prédiction
        test_indicators = {
            'RSI': 45,
            'MACD': 2,
            'Trend': 1,
            'close': 45000
        }
        
        prob = learning.predict_trade_success(test_indicators)
        print(f"\n🎯 Prédiction pour de nouveaux indicateurs:")
        print(f"  RSI: {test_indicators['RSI']}")
        print(f"  MACD: {test_indicators['MACD']}")
        print(f"  Trend: {test_indicators['Trend']}")
        print(f"  Probabilité de succès: {prob:.1%}")
    
    # Obtenir les recommandations
    print("\n💡 Recommandations d'optimisation:")
    recommendations = learning.get_optimization_recommendations()
    for rec in recommendations:
        print(f"  {rec}")
    
    # Nettoyer
    import os
    if os.path.exists('demo_trade_history.json'):
        os.remove('demo_trade_history.json')


def demo_risk_manager():
    """Démontre la gestion des risques"""
    print("\n" + "="*80)
    print("DÉMONSTRATION: Gestionnaire de Risques")
    print("="*80)
    
    risk_manager = RiskManager(
        max_risk_per_trade=0.02,
        max_daily_loss=0.05,
        initial_capital=10000
    )
    
    print(f"\nConfiguration:")
    print(f"  Capital initial: {risk_manager.initial_capital}")
    print(f"  Risque max par trade: {risk_manager.max_risk_per_trade:.1%}")
    print(f"  Perte max journalière: {risk_manager.max_daily_loss:.1%}")
    
    # Test 1: Peut-on ouvrir une position?
    print(f"\n✅ Peut ouvrir une position? {risk_manager.can_open_position()}")
    
    # Test 2: Calculer la taille de position
    entry_price = 45000
    atr = 500
    position_size = risk_manager.calculate_position_size(entry_price, atr)
    print(f"\n📏 Calcul de position:")
    print(f"  Prix d'entrée: {entry_price}")
    print(f"  ATR: {atr}")
    print(f"  Taille calculée: {position_size:.4f}")
    
    # Test 3: Simuler quelques trades
    print(f"\n💼 Simulation de trades:")
    profits = [150, -80, 200, -50, 100]
    
    for i, profit in enumerate(profits):
        risk_manager.record_trade(profit)
        print(f"  Trade {i+1}: {'+' if profit > 0 else ''}{profit:.2f}")
    
    # Statut final
    status = risk_manager.get_status()
    print(f"\n📊 Statut final:")
    print(f"  Capital actuel: {status['current_capital']:.2f}")
    print(f"  P&L total: {status['total_profit_loss']:.2f}")
    print(f"  Retour: {status['return_percentage']:.2f}%")
    print(f"  P&L journalier: {status['daily_profit_loss']:.2f}")
    print(f"  Peut trader: {status['can_trade']}")


def demo_full_system():
    """Démontre le système complet"""
    print("\n" + "="*80)
    print("DÉMONSTRATION: Système Complet de Trading")
    print("="*80)
    
    # Configuration
    config = {
        'symbol': 'BTC-USD',
        'interval': '1h',
        'period': '1mo',
        'initial_capital': 10000,
        'max_risk_per_trade': 0.02,
        'max_daily_loss': 0.05,
        'min_confidence': 0.5,
        'demo_mode': True
    }
    
    print(f"\nConfiguration:")
    print(f"  Symbole: {config['symbol']}")
    print(f"  Capital: {config['initial_capital']}")
    print(f"  Risque/trade: {config['max_risk_per_trade']:.1%}")
    
    # Créer le moteur
    engine = TradingEngine(config)
    
    # Récupérer les données réelles
    print(f"\n📡 Récupération des données de marché...")
    fetcher = MarketDataFetcher()
    market_data = fetcher.fetch_data(config['symbol'], period='1mo', interval='1h')
    
    if market_data is not None and not market_data.empty:
        print(f"✅ Données récupérées: {len(market_data)} périodes")
        print(f"  Période: {market_data.index[0]} à {market_data.index[-1]}")
        print(f"  Prix actuel: {market_data['close'].iloc[-1]:.2f}")
        
        # Analyser et potentiellement trader
        print(f"\n🔍 Analyse du marché...")
        result = engine.analyze_and_trade(market_data, config['symbol'])
        
        print(f"\n📊 Résultat de l'analyse:")
        print(f"  Signal: {result['signal']}")
        print(f"  Force: {result['strength']}")
        if result['reasons']:
            print(f"  Raisons: {', '.join(result['reasons'])}")
        print(f"  Trade exécuté: {result['trade_executed']}")
        
        # Afficher le statut
        status = engine.get_status()
        print(f"\n📈 Statut du système:")
        print(f"  Position ouverte: {status['current_position'] is not None}")
        print(f"  Capital: {status['risk_status']['current_capital']:.2f}")
        print(f"  Modèle entraîné: {status['model_trained']}")
        
    else:
        print("❌ Impossible de récupérer les données de marché")
        print("   (Cela peut être dû à une connexion internet ou à des limites d'API)")


def main():
    """Lance toutes les démonstrations"""
    print("\n" + "="*80)
    print("EMPIRE AGENT IA 3.1 - DÉMONSTRATION COMPLÈTE")
    print("="*80)
    print("\nCe script démontre toutes les fonctionnalités du système:")
    print("1. Analyseur de graphiques")
    print("2. Système d'apprentissage")
    print("3. Gestionnaire de risques")
    print("4. Système complet")
    
    input("\nAppuyez sur Entrée pour commencer...")
    
    try:
        demo_chart_analyzer()
        input("\nAppuyez sur Entrée pour continuer...")
        
        demo_learning_system()
        input("\nAppuyez sur Entrée pour continuer...")
        
        demo_risk_manager()
        input("\nAppuyez sur Entrée pour continuer...")
        
        demo_full_system()
        
        print("\n" + "="*80)
        print("DÉMONSTRATION TERMINÉE")
        print("="*80)
        print("\n✅ Toutes les fonctionnalités ont été démontrées avec succès!")
        print("\n📚 Pour utiliser le système:")
        print("  - Mode démo: python main.py demo 10")
        print("  - Mode continu: python main.py")
        print("\n📖 Consultez README.md pour plus d'informations")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Démonstration interrompue")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
