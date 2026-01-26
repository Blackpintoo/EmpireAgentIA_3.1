"""
Gestionnaire de risques pour le trading
Contrôle l'exposition au risque et protège le capital
"""

from datetime import datetime, timedelta
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Gère les risques de trading pour protéger le capital
    """
    
    def __init__(self, max_risk_per_trade: float = 0.02, 
                 max_daily_loss: float = 0.05,
                 initial_capital: float = 10000):
        """
        Args:
            max_risk_per_trade: Risque maximum par trade (ex: 0.02 = 2%)
            max_daily_loss: Perte maximum journalière (ex: 0.05 = 5%)
            initial_capital: Capital initial
        """
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        
        self.daily_trades = []
        self.daily_profit_loss = 0.0
        self.total_profit_loss = 0.0
        
        self.max_positions = 3  # Maximum de positions simultanées
        self.open_positions = 0
        
        logger.info(f"RiskManager initialisé: Capital={initial_capital}, "
                   f"Risk/Trade={max_risk_per_trade:.1%}, "
                   f"Max Daily Loss={max_daily_loss:.1%}")
    
    def can_open_position(self) -> bool:
        """
        Vérifie si une nouvelle position peut être ouverte
        
        Returns:
            True si le trade est autorisé, False sinon
        """
        # Vérifier la limite de positions
        if self.open_positions >= self.max_positions:
            logger.warning(f"Limite de positions atteinte ({self.open_positions}/{self.max_positions})")
            return False
        
        # Vérifier la perte journalière
        self._update_daily_tracking()
        daily_loss_percentage = abs(self.daily_profit_loss) / self.current_capital
        
        if self.daily_profit_loss < 0 and daily_loss_percentage >= self.max_daily_loss:
            logger.warning(f"Limite de perte journalière atteinte: {daily_loss_percentage:.1%}")
            return False
        
        # Vérifier le capital disponible
        if self.current_capital <= self.initial_capital * 0.5:
            logger.warning(f"Capital trop bas: {self.current_capital:.2f}")
            return False
        
        return True
    
    def calculate_position_size(self, entry_price: float, atr: float) -> float:
        """
        Calcule la taille de position appropriée basée sur le risque
        
        Args:
            entry_price: Prix d'entrée
            atr: Average True Range pour évaluer la volatilité
            
        Returns:
            Taille de la position
        """
        # Risque maximum en capital
        max_risk_capital = self.current_capital * self.max_risk_per_trade
        
        # Distance du stop loss basée sur l'ATR (2x ATR)
        stop_distance = atr * 2
        
        # Taille de position pour ne pas dépasser le risque max
        if stop_distance > 0:
            position_size = max_risk_capital / stop_distance
        else:
            position_size = 0
        
        # Limiter la position à un pourcentage du capital
        max_position_value = self.current_capital * 0.3  # Max 30% du capital par position
        max_position_size = max_position_value / entry_price
        
        position_size = min(position_size, max_position_size)
        
        logger.info(f"Taille de position calculée: {position_size:.4f} "
                   f"(Risque: {max_risk_capital:.2f}, Stop: {stop_distance:.2f})")
        
        return position_size
    
    def record_trade(self, profit: float):
        """
        Enregistre un trade terminé
        
        Args:
            profit: Profit ou perte du trade
        """
        trade_record = {
            'timestamp': datetime.now(),
            'profit': profit
        }
        
        self.daily_trades.append(trade_record)
        self.daily_profit_loss += profit
        self.total_profit_loss += profit
        self.current_capital += profit
        
        logger.info(f"Trade enregistré: Profit={profit:.2f}, "
                   f"Capital={self.current_capital:.2f}, "
                   f"P&L journalier={self.daily_profit_loss:.2f}")
    
    def _update_daily_tracking(self):
        """
        Met à jour le suivi journalier (réinitialise chaque jour)
        """
        now = datetime.now()
        
        # Filtrer les trades du jour
        today_trades = [
            t for t in self.daily_trades 
            if t['timestamp'].date() == now.date()
        ]
        
        # Si nouveau jour, réinitialiser
        if not today_trades and self.daily_trades:
            logger.info("Nouveau jour de trading - Réinitialisation des compteurs journaliers")
            self.daily_trades = []
            self.daily_profit_loss = 0.0
        else:
            self.daily_trades = today_trades
            self.daily_profit_loss = sum(t['profit'] for t in today_trades)
    
    def get_status(self) -> Dict:
        """
        Retourne le statut du risk manager
        """
        self._update_daily_tracking()
        
        return {
            'current_capital': self.current_capital,
            'initial_capital': self.initial_capital,
            'total_profit_loss': self.total_profit_loss,
            'daily_profit_loss': self.daily_profit_loss,
            'return_percentage': ((self.current_capital - self.initial_capital) / 
                                 self.initial_capital * 100),
            'open_positions': self.open_positions,
            'max_positions': self.max_positions,
            'can_trade': self.can_open_position(),
            'daily_trades_count': len(self.daily_trades)
        }
    
    def adjust_risk_parameters(self, win_rate: float):
        """
        Ajuste les paramètres de risque en fonction de la performance
        
        Args:
            win_rate: Taux de réussite actuel (0-1)
        """
        # Si le taux de réussite est bon, on peut augmenter légèrement le risque
        if win_rate > 0.7:
            self.max_risk_per_trade = min(0.03, self.max_risk_per_trade * 1.1)
            logger.info(f"Risque par trade augmenté à {self.max_risk_per_trade:.1%}")
        # Si mauvais, on réduit le risque
        elif win_rate < 0.4:
            self.max_risk_per_trade = max(0.01, self.max_risk_per_trade * 0.9)
            logger.info(f"Risque par trade réduit à {self.max_risk_per_trade:.1%}")
