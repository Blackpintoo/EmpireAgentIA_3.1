"""
Système d'apprentissage qui apprend des trades réussis et ratés
Optimise constamment les stratégies pour améliorer les performances
"""

import json
import os
from datetime import datetime
from typing import Dict, List
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
import logging

logger = logging.getLogger(__name__)


class LearningSystem:
    """
    Système d'apprentissage automatique qui améliore les décisions de trading
    en apprenant des succès et des échecs passés
    """
    
    def __init__(self, history_file: str = 'trade_history.json'):
        self.history_file = history_file
        self.trade_history = []
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()
        self.is_trained = False
        self.performance_metrics = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'win_rate': 0.0,
            'average_profit': 0.0,
            'total_profit': 0.0
        }
        self._load_history()
        logger.info("LearningSystem initialisé")
    
    def _load_history(self):
        """Charge l'historique des trades depuis le fichier"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    self.trade_history = json.load(f)
                logger.info(f"Historique chargé: {len(self.trade_history)} trades")
                self._update_metrics()
            except Exception as e:
                logger.error(f"Erreur lors du chargement de l'historique: {e}")
                self.trade_history = []
        else:
            logger.info("Pas d'historique existant, démarrage avec historique vide")
    
    def _save_history(self):
        """Sauvegarde l'historique des trades"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.trade_history, f, indent=2)
            logger.info(f"Historique sauvegardé: {len(self.trade_history)} trades")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de l'historique: {e}")
    
    def record_trade(self, trade_data: Dict):
        """
        Enregistre un trade pour l'apprentissage
        
        Args:
            trade_data: Dict contenant les détails du trade
                - action: 'BUY' ou 'SELL'
                - entry_price: prix d'entrée
                - exit_price: prix de sortie
                - profit: profit/perte
                - success: True/False
                - indicators: valeurs des indicateurs au moment du trade
                - timestamp: date et heure du trade
        """
        trade_record = {
            'timestamp': trade_data.get('timestamp', datetime.now().isoformat()),
            'action': trade_data['action'],
            'entry_price': trade_data['entry_price'],
            'exit_price': trade_data.get('exit_price', 0),
            'profit': trade_data.get('profit', 0),
            'profit_percentage': trade_data.get('profit_percentage', 0),
            'success': trade_data['success'],
            'indicators': trade_data['indicators'],
            'reasons': trade_data.get('reasons', [])
        }
        
        self.trade_history.append(trade_record)
        self._update_metrics()
        self._save_history()
        
        logger.info(f"Trade enregistré: {trade_record['action']} - "
                   f"Profit: {trade_record['profit']:.2f} - "
                   f"Succès: {trade_record['success']}")
    
    def _update_metrics(self):
        """Met à jour les métriques de performance"""
        if not self.trade_history:
            return
        
        self.performance_metrics['total_trades'] = len(self.trade_history)
        self.performance_metrics['successful_trades'] = sum(
            1 for t in self.trade_history if t['success']
        )
        self.performance_metrics['failed_trades'] = (
            self.performance_metrics['total_trades'] - 
            self.performance_metrics['successful_trades']
        )
        
        if self.performance_metrics['total_trades'] > 0:
            self.performance_metrics['win_rate'] = (
                self.performance_metrics['successful_trades'] / 
                self.performance_metrics['total_trades']
            )
        
        profits = [t['profit'] for t in self.trade_history]
        self.performance_metrics['total_profit'] = sum(profits)
        self.performance_metrics['average_profit'] = (
            self.performance_metrics['total_profit'] / 
            self.performance_metrics['total_trades']
            if self.performance_metrics['total_trades'] > 0 else 0
        )
    
    def train_model(self):
        """
        Entraîne le modèle d'apprentissage sur l'historique des trades
        """
        if len(self.trade_history) < 10:
            logger.warning(f"Pas assez de données pour l'entraînement "
                         f"({len(self.trade_history)} trades). Minimum: 10")
            return False
        
        logger.info("Entraînement du modèle d'apprentissage...")
        
        # Préparer les features et labels
        X = []
        y = []
        
        for trade in self.trade_history:
            indicators = trade['indicators']
            features = [
                indicators.get('RSI', 50),
                indicators.get('MACD', 0),
                indicators.get('Trend', 0),
                indicators.get('close', 100)
            ]
            X.append(features)
            y.append(1 if trade['success'] else 0)
        
        X = np.array(X)
        y = np.array(y)
        
        # Normaliser les features
        X_scaled = self.scaler.fit_transform(X)
        
        # Entraîner le modèle
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        # Calculer la précision
        accuracy = self.model.score(X_scaled, y)
        logger.info(f"Modèle entraîné avec {len(X)} exemples. Précision: {accuracy:.2%}")
        
        return True
    
    def predict_trade_success(self, indicators: Dict) -> float:
        """
        Prédit la probabilité de succès d'un trade basé sur les indicateurs
        
        Returns:
            Probabilité de succès entre 0 et 1
        """
        if not self.is_trained:
            logger.warning("Modèle pas encore entraîné, utilisation des règles par défaut")
            return 0.5
        
        features = [
            indicators.get('RSI', 50),
            indicators.get('MACD', 0),
            indicators.get('Trend', 0),
            indicators.get('close', 100)
        ]
        
        X = np.array([features])
        X_scaled = self.scaler.transform(X)
        
        # Probabilité de succès
        prob = self.model.predict_proba(X_scaled)[0][1]
        
        return prob
    
    def get_performance_report(self) -> Dict:
        """
        Retourne un rapport de performance détaillé
        """
        report = self.performance_metrics.copy()
        
        # Analyse des trades récents (derniers 10)
        recent_trades = self.trade_history[-10:] if len(self.trade_history) >= 10 else self.trade_history
        if recent_trades:
            recent_success = sum(1 for t in recent_trades if t['success'])
            report['recent_win_rate'] = recent_success / len(recent_trades)
            report['recent_profit'] = sum(t['profit'] for t in recent_trades)
        else:
            report['recent_win_rate'] = 0
            report['recent_profit'] = 0
        
        # Meilleurs et pires trades
        if self.trade_history:
            sorted_by_profit = sorted(self.trade_history, key=lambda x: x['profit'])
            report['best_trade'] = sorted_by_profit[-1]['profit']
            report['worst_trade'] = sorted_by_profit[0]['profit']
        
        return report
    
    def get_optimization_recommendations(self) -> List[str]:
        """
        Génère des recommandations d'optimisation basées sur l'historique
        """
        recommendations = []
        metrics = self.performance_metrics
        
        if metrics['total_trades'] == 0:
            recommendations.append("Aucun trade enregistré. Commencez à trader pour obtenir des recommandations.")
            return recommendations
        
        # Recommandations basées sur le taux de réussite
        if metrics['win_rate'] < 0.4:
            recommendations.append(
                f"⚠️ Taux de réussite faible ({metrics['win_rate']:.1%}). "
                "Considérez une stratégie plus conservative."
            )
        elif metrics['win_rate'] > 0.7:
            recommendations.append(
                f"✅ Excellent taux de réussite ({metrics['win_rate']:.1%}). "
                "Maintenez cette stratégie."
            )
        
        # Recommandations basées sur le profit moyen
        if metrics['average_profit'] < 0:
            recommendations.append(
                f"⚠️ Profit moyen négatif ({metrics['average_profit']:.2f}). "
                "Révision urgente de la stratégie nécessaire."
            )
        
        # Analyse des patterns de succès
        if len(self.trade_history) >= 10:
            successful_trades = [t for t in self.trade_history if t['success']]
            if successful_trades:
                avg_rsi_success = np.mean([
                    t['indicators'].get('RSI', 50) 
                    for t in successful_trades
                ])
                recommendations.append(
                    f"📊 Les trades réussis ont un RSI moyen de {avg_rsi_success:.1f}. "
                    "Utilisez cette information pour optimiser l'entrée."
                )
        
        # Recommandations pour l'entraînement du modèle
        if not self.is_trained and len(self.trade_history) >= 10:
            recommendations.append(
                "🤖 Assez de données disponibles. Entraînez le modèle d'apprentissage "
                "pour améliorer les prédictions."
            )
        
        return recommendations
    
    def save_model(self, model_file: str = 'trading_model.pkl'):
        """Sauvegarde le modèle entraîné"""
        if self.is_trained:
            joblib.dump({
                'model': self.model,
                'scaler': self.scaler
            }, model_file)
            logger.info(f"Modèle sauvegardé dans {model_file}")
    
    def load_model(self, model_file: str = 'trading_model.pkl'):
        """Charge un modèle pré-entraîné"""
        if os.path.exists(model_file):
            data = joblib.load(model_file)
            self.model = data['model']
            self.scaler = data['scaler']
            self.is_trained = True
            logger.info(f"Modèle chargé depuis {model_file}")
