"""
Test simple des modules principaux
"""
import sys
import os

from src.chart_analyzer import ChartAnalyzer
from src.learning_system import LearningSystem
from src.risk_manager import RiskManager
import pandas as pd
import numpy as np

print('Testing Chart Analyzer...')
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
df_with_indicators = analyzer.calculate_indicators(df)
signals = analyzer.analyze_signals(df_with_indicators)
print(f'✓ Chart Analyzer: Signal={signals["signal"]}, Strength={signals["strength"]}')

print('\nTesting Learning System...')
learning = LearningSystem(history_file='/tmp/test_history.json')
test_trade = {
    'action': 'BUY',
    'entry_price': 100,
    'exit_price': 105,
    'profit': 5,
    'profit_percentage': 5,
    'success': True,
    'indicators': {'RSI': 50, 'MACD': 0, 'Trend': 1, 'close': 100},
    'reasons': ['Test']
}
learning.record_trade(test_trade)
print(f'✓ Learning System: {learning.performance_metrics["total_trades"]} trades recorded')

print('\nTesting Risk Manager...')
risk = RiskManager(initial_capital=10000)
can_trade = risk.can_open_position()
position_size = risk.calculate_position_size(100, 2)
print(f'✓ Risk Manager: Can trade={can_trade}, Position size={position_size:.4f}')

print('\n' + '='*60)
print('ALL TESTS PASSED ✓')
print('='*60)
