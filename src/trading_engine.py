"""
Moteur de trading principal - Système autonome
Gère l'exécution des trades et la coordination entre les modules
"""

import pandas as pd
from datetime import datetime
from typing import Dict, Optional
import logging
from .chart_analyzer import ChartAnalyzer
from .learning_system import LearningSystem
from .risk_manager import RiskManager

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Moteur de trading autonome qui:
    - Analyse les graphiques en continu
    - Prend des décisions de trading
    - Apprend de ses erreurs et succès
    - S'optimise automatiquement
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.chart_analyzer = ChartAnalyzer()
        self.learning_system = LearningSystem()
        self.risk_manager = RiskManager(
            max_risk_per_trade=config.get('max_risk_per_trade', 0.02),
            max_daily_loss=config.get('max_daily_loss', 0.05),
            initial_capital=config.get('initial_capital', 10000)
        )
        
        self.current_position = None
        self.is_running = False
        
        logger.info("TradingEngine initialisé avec configuration:")
        logger.info(f"  Capital initial: {config.get('initial_capital', 10000)}")
        logger.info(f"  Risque max par trade: {config.get('max_risk_per_trade', 0.02):.1%}")
        logger.info(f"  Perte max journalière: {config.get('max_daily_loss', 0.05):.1%}")
    
    def analyze_and_trade(self, market_data: pd.DataFrame, symbol: str) -> Dict:
        """
        Analyse le marché et prend une décision de trading
        
        Args:
            market_data: DataFrame avec les données OHLCV
            symbol: Symbole du marché (ex: 'BTC/USD')
            
        Returns:
            Dict avec les détails de la décision
        """
        logger.info(f"Analyse du marché pour {symbol}...")
        
        # Calculer les indicateurs techniques
        df_with_indicators = self.chart_analyzer.calculate_indicators(market_data.copy())
        
        # Analyser les signaux
        signal_analysis = self.chart_analyzer.analyze_signals(df_with_indicators)
        
        # Vérifier les risques
        can_trade = self.risk_manager.can_open_position()
        
        if not can_trade:
            logger.warning("Trading bloqué par le risk manager")
            signal_analysis['signal'] = 'HOLD'
            signal_analysis['risk_blocked'] = True
        
        # Utiliser le système d'apprentissage pour ajuster la décision
        if signal_analysis['signal'] in ['BUY', 'SELL']:
            success_probability = self.learning_system.predict_trade_success(
                signal_analysis['indicators']
            )
            
            logger.info(f"Probabilité de succès prédite: {success_probability:.1%}")
            
            # Ne trader que si la probabilité de succès est suffisante
            min_confidence = self.config.get('min_confidence', 0.5)
            if success_probability < min_confidence:
                logger.info(f"Probabilité trop faible ({success_probability:.1%} < {min_confidence:.1%})")
                signal_analysis['signal'] = 'HOLD'
                signal_analysis['low_confidence'] = True
        
        # Exécuter le trade si approprié
        trade_result = None
        if signal_analysis['signal'] == 'BUY' and self.current_position is None:
            trade_result = self._execute_buy(df_with_indicators, symbol, signal_analysis)
        elif signal_analysis['signal'] == 'SELL' and self.current_position is not None:
            trade_result = self._execute_sell(df_with_indicators, symbol, signal_analysis)
        
        return {
            'signal': signal_analysis['signal'],
            'strength': signal_analysis['strength'],
            'reasons': signal_analysis['reasons'],
            'trade_executed': trade_result is not None,
            'trade_result': trade_result,
            'risk_status': self.risk_manager.get_status()
        }
    
    def _execute_buy(self, df: pd.DataFrame, symbol: str, signal_analysis: Dict) -> Dict:
        """Exécute un ordre d'achat"""
        current_price = df.iloc[-1]['close']
        
        # Calculer la taille de position
        position_size = self.risk_manager.calculate_position_size(
            current_price,
            df.iloc[-1]['ATR']
        )
        
        if position_size == 0:
            logger.warning("Taille de position = 0, trade annulé")
            return None
        
        # Calculer stop loss et take profit
        support, resistance = self.chart_analyzer.calculate_support_resistance(df)
        stop_loss = support if support else current_price * 0.98
        take_profit = resistance if resistance else current_price * 1.03
        
        self.current_position = {
            'symbol': symbol,
            'action': 'BUY',
            'entry_price': current_price,
            'entry_time': datetime.now().isoformat(),
            'size': position_size,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'indicators': signal_analysis['indicators'],
            'reasons': signal_analysis['reasons']
        }
        
        # Incrémenter le compteur de positions
        self.risk_manager.open_positions += 1
        
        logger.info(f"ACHAT exécuté: {symbol} @ {current_price:.2f}")
        logger.info(f"  Taille: {position_size:.4f}")
        logger.info(f"  Stop Loss: {stop_loss:.2f}")
        logger.info(f"  Take Profit: {take_profit:.2f}")
        
        return self.current_position
    
    def _execute_sell(self, df: pd.DataFrame, symbol: str, signal_analysis: Dict) -> Dict:
        """Exécute un ordre de vente et clôture la position"""
        if self.current_position is None:
            return None
        
        exit_price = df.iloc[-1]['close']
        entry_price = self.current_position['entry_price']
        position_size = self.current_position['size']
        
        # Calculer le profit/perte
        profit = (exit_price - entry_price) * position_size
        profit_percentage = ((exit_price - entry_price) / entry_price) * 100
        
        success = profit > 0
        
        # Enregistrer le trade pour l'apprentissage
        trade_data = {
            'action': self.current_position['action'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit': profit,
            'profit_percentage': profit_percentage,
            'success': success,
            'indicators': self.current_position['indicators'],
            'reasons': self.current_position['reasons'],
            'timestamp': datetime.now().isoformat()
        }
        
        self.learning_system.record_trade(trade_data)
        self.risk_manager.record_trade(profit)
        
        # Décrémenter le compteur de positions
        self.risk_manager.open_positions = max(0, self.risk_manager.open_positions - 1)
        
        logger.info(f"VENTE exécutée: {symbol} @ {exit_price:.2f}")
        logger.info(f"  Profit/Perte: {profit:.2f} ({profit_percentage:.2f}%)")
        logger.info(f"  Résultat: {'SUCCÈS' if success else 'ÉCHEC'}")
        
        result = {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit': profit,
            'profit_percentage': profit_percentage,
            'success': success
        }
        
        self.current_position = None
        return result
    
    def check_position_management(self, df: pd.DataFrame):
        """
        Vérifie et gère la position actuelle (stop loss, take profit)
        """
        if self.current_position is None:
            return None
        
        current_price = df.iloc[-1]['close']
        
        # Vérifier stop loss
        if current_price <= self.current_position['stop_loss']:
            logger.warning(f"Stop Loss atteint: {current_price:.2f} <= {self.current_position['stop_loss']:.2f}")
            return self._execute_sell(df, self.current_position['symbol'], {'signal': 'SELL', 'reasons': ['Stop Loss']})
        
        # Vérifier take profit
        if current_price >= self.current_position['take_profit']:
            logger.info(f"Take Profit atteint: {current_price:.2f} >= {self.current_position['take_profit']:.2f}")
            return self._execute_sell(df, self.current_position['symbol'], {'signal': 'SELL', 'reasons': ['Take Profit']})
        
        return None
    
    def optimize(self):
        """
        Optimise le système en entraînant le modèle d'apprentissage
        """
        logger.info("Démarrage de l'optimisation du système...")
        
        # Entraîner le modèle d'apprentissage
        if self.learning_system.train_model():
            logger.info("Modèle d'apprentissage mis à jour avec succès")
            self.learning_system.save_model()
        
        # Obtenir les recommandations
        recommendations = self.learning_system.get_optimization_recommendations()
        
        logger.info("Recommandations d'optimisation:")
        for rec in recommendations:
            logger.info(f"  {rec}")
        
        # Obtenir le rapport de performance
        performance = self.learning_system.get_performance_report()
        logger.info("Performance actuelle:")
        logger.info(f"  Total trades: {performance['total_trades']}")
        logger.info(f"  Taux de réussite: {performance['win_rate']:.1%}")
        logger.info(f"  Profit total: {performance['total_profit']:.2f}")
        logger.info(f"  Profit moyen: {performance['average_profit']:.2f}")
        
        return {
            'recommendations': recommendations,
            'performance': performance
        }
    
    def get_status(self) -> Dict:
        """Retourne le statut actuel du système"""
        return {
            'is_running': self.is_running,
            'current_position': self.current_position,
            'performance': self.learning_system.get_performance_report(),
            'risk_status': self.risk_manager.get_status(),
            'model_trained': self.learning_system.is_trained
        }
