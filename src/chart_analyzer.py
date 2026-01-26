"""
Module d'analyse de graphiques et d'indicateurs techniques
Analyse constante des graphiques pour détecter les opportunités de trading
"""

import pandas as pd
import numpy as np
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
from typing import Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChartAnalyzer:
    """
    Classe pour l'analyse technique des graphiques
    Utilise de multiples indicateurs pour évaluer les opportunités de trading
    """
    
    def __init__(self):
        self.indicators = {}
        logger.info("ChartAnalyzer initialisé")
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcule tous les indicateurs techniques sur les données de prix
        
        Args:
            df: DataFrame avec colonnes 'open', 'high', 'low', 'close', 'volume'
            
        Returns:
            DataFrame enrichi avec tous les indicateurs
        """
        logger.info("Calcul des indicateurs techniques...")
        
        # Moyennes mobiles
        df['SMA_20'] = SMAIndicator(close=df['close'], window=20).sma_indicator()
        df['SMA_50'] = SMAIndicator(close=df['close'], window=50).sma_indicator()
        df['EMA_12'] = EMAIndicator(close=df['close'], window=12).ema_indicator()
        df['EMA_26'] = EMAIndicator(close=df['close'], window=26).ema_indicator()
        
        # MACD
        macd = MACD(close=df['close'])
        df['MACD'] = macd.macd()
        df['MACD_signal'] = macd.macd_signal()
        df['MACD_diff'] = macd.macd_diff()
        
        # RSI
        df['RSI'] = RSIIndicator(close=df['close'], window=14).rsi()
        
        # Stochastic
        stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'])
        df['Stoch_K'] = stoch.stoch()
        df['Stoch_D'] = stoch.stoch_signal()
        
        # Bollinger Bands
        bollinger = BollingerBands(close=df['close'])
        df['BB_high'] = bollinger.bollinger_hband()
        df['BB_mid'] = bollinger.bollinger_mavg()
        df['BB_low'] = bollinger.bollinger_lband()
        df['BB_width'] = bollinger.bollinger_wband()
        
        # ATR (Average True Range)
        df['ATR'] = AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close']
        ).average_true_range()
        
        # Volume indicators
        df['OBV'] = OnBalanceVolumeIndicator(
            close=df['close'], 
            volume=df['volume']
        ).on_balance_volume()
        
        # Tendance
        df['Trend'] = self._calculate_trend(df)
        
        logger.info(f"Indicateurs calculés pour {len(df)} périodes")
        return df
    
    def _calculate_trend(self, df: pd.DataFrame) -> pd.Series:
        """
        Détermine la tendance du marché (1=haussier, -1=baissier, 0=neutre)
        """
        trend = pd.Series(0, index=df.index)
        
        # Tendance basée sur les moyennes mobiles
        if 'SMA_20' in df.columns and 'SMA_50' in df.columns:
            trend[(df['SMA_20'] > df['SMA_50']) & (df['close'] > df['SMA_20'])] = 1
            trend[(df['SMA_20'] < df['SMA_50']) & (df['close'] < df['SMA_20'])] = -1
        
        return trend
    
    def analyze_signals(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        Analyse les signaux de trading basés sur les indicateurs
        
        Returns:
            Dict avec signal d'achat/vente et force du signal
        """
        if len(df) < 50:
            return {'signal': 'HOLD', 'strength': 0, 'reasons': []}
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        buy_signals = []
        sell_signals = []
        
        # Signal RSI
        if latest['RSI'] < 30:
            buy_signals.append('RSI oversold')
        elif latest['RSI'] > 70:
            sell_signals.append('RSI overbought')
        
        # Signal MACD
        if prev['MACD'] < prev['MACD_signal'] and latest['MACD'] > latest['MACD_signal']:
            buy_signals.append('MACD bullish cross')
        elif prev['MACD'] > prev['MACD_signal'] and latest['MACD'] < latest['MACD_signal']:
            sell_signals.append('MACD bearish cross')
        
        # Signal Bollinger Bands
        if latest['close'] < latest['BB_low']:
            buy_signals.append('Price below BB lower band')
        elif latest['close'] > latest['BB_high']:
            sell_signals.append('Price above BB upper band')
        
        # Signal Stochastic
        if latest['Stoch_K'] < 20 and latest['Stoch_K'] > prev['Stoch_K']:
            buy_signals.append('Stochastic oversold reversal')
        elif latest['Stoch_K'] > 80 and latest['Stoch_K'] < prev['Stoch_K']:
            sell_signals.append('Stochastic overbought reversal')
        
        # Signal de tendance
        if latest['Trend'] == 1 and latest['close'] > latest['SMA_20']:
            buy_signals.append('Uptrend confirmed')
        elif latest['Trend'] == -1 and latest['close'] < latest['SMA_20']:
            sell_signals.append('Downtrend confirmed')
        
        # Décision finale
        buy_strength = len(buy_signals)
        sell_strength = len(sell_signals)
        
        if buy_strength > sell_strength and buy_strength >= 2:
            signal = 'BUY'
            strength = buy_strength
            reasons = buy_signals
        elif sell_strength > buy_strength and sell_strength >= 2:
            signal = 'SELL'
            strength = sell_strength
            reasons = sell_signals
        else:
            signal = 'HOLD'
            strength = 0
            reasons = []
        
        return {
            'signal': signal,
            'strength': strength,
            'reasons': reasons,
            'indicators': {
                'RSI': latest['RSI'],
                'MACD': latest['MACD'],
                'Trend': latest['Trend'],
                'close': latest['close']
            }
        }
    
    def calculate_support_resistance(self, df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
        """
        Calcule les niveaux de support et résistance
        """
        if len(df) < window:
            return None, None
        
        recent_data = df.tail(window)
        support = recent_data['low'].min()
        resistance = recent_data['high'].max()
        
        return support, resistance
