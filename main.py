"""
Application principale du système de trading autonome EmpireAgentIA 3.1
Lance et gère le système de trading
"""

import time
import logging
from datetime import datetime
from src.trading_engine import TradingEngine
from src.market_data import MarketDataFetcher

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class TradingApplication:
    """
    Application principale qui orchestre le système de trading autonome
    """
    
    def __init__(self, config: dict = None):
        """
        Initialise l'application de trading
        
        Args:
            config: Configuration du système
        """
        if config is None:
            config = self._get_default_config()
        
        self.config = config
        self.trading_engine = TradingEngine(config)
        self.market_data_fetcher = MarketDataFetcher()
        self.is_running = False
        
        logger.info("=" * 80)
        logger.info("EmpireAgentIA 3.1 - Système de Trading Autonome")
        logger.info("=" * 80)
        logger.info(f"Symbole: {config['symbol']}")
        logger.info(f"Intervalle: {config['interval']}")
        logger.info(f"Mode: {'DEMO' if config.get('demo_mode', True) else 'LIVE'}")
        logger.info("=" * 80)
    
    def _get_default_config(self) -> dict:
        """Retourne la configuration par défaut"""
        return {
            'symbol': 'BTC-USD',  # Symbole à trader
            'interval': '1h',  # Intervalle de temps
            'period': '3mo',  # Période historique
            'initial_capital': 10000,  # Capital initial
            'max_risk_per_trade': 0.02,  # 2% de risque par trade
            'max_daily_loss': 0.05,  # 5% de perte max par jour
            'min_confidence': 0.6,  # Confiance minimale pour trader (60%)
            'demo_mode': True,  # Mode démo par défaut
            'optimization_interval': 100,  # Optimiser tous les 100 cycles
            'check_interval': 60  # Vérifier le marché toutes les 60 secondes
        }
    
    def run_single_cycle(self):
        """
        Exécute un cycle d'analyse et de trading
        """
        try:
            # Récupérer les données de marché
            market_data = self.market_data_fetcher.fetch_data(
                self.config['symbol'],
                period=self.config['period'],
                interval=self.config['interval']
            )
            
            if market_data is None or market_data.empty:
                logger.error("Impossible de récupérer les données de marché")
                return
            
            # Vérifier la gestion de position actuelle (stop loss, take profit)
            self.trading_engine.check_position_management(market_data)
            
            # Analyser et trader
            result = self.trading_engine.analyze_and_trade(
                market_data,
                self.config['symbol']
            )
            
            logger.info(f"Signal: {result['signal']} (Force: {result['strength']})")
            if result['reasons']:
                logger.info(f"Raisons: {', '.join(result['reasons'])}")
            
            if result['trade_executed']:
                logger.info("✅ Trade exécuté!")
            
        except Exception as e:
            logger.error(f"Erreur dans le cycle de trading: {e}", exc_info=True)
    
    def run_continuous(self):
        """
        Lance le système en mode continu
        """
        self.is_running = True
        cycle_count = 0
        
        logger.info("🚀 Démarrage du système de trading autonome...")
        
        try:
            while self.is_running:
                cycle_count += 1
                logger.info(f"\n{'=' * 80}")
                logger.info(f"Cycle #{cycle_count} - {datetime.now()}")
                logger.info(f"{'=' * 80}")
                
                # Exécuter un cycle de trading
                self.run_single_cycle()
                
                # Optimisation périodique
                if cycle_count % self.config['optimization_interval'] == 0:
                    logger.info("\n🔧 Optimisation du système...")
                    optimization_result = self.trading_engine.optimize()
                    
                    logger.info("\n📊 Recommandations:")
                    for rec in optimization_result['recommendations']:
                        logger.info(f"  {rec}")
                
                # Afficher le statut
                status = self.trading_engine.get_status()
                logger.info(f"\n📈 Statut du système:")
                logger.info(f"  Position actuelle: {status['current_position'] is not None}")
                logger.info(f"  Capital: {status['risk_status']['current_capital']:.2f}")
                logger.info(f"  P&L Total: {status['risk_status']['total_profit_loss']:.2f}")
                logger.info(f"  Retour: {status['risk_status']['return_percentage']:.2f}%")
                logger.info(f"  Taux de réussite: {status['performance']['win_rate']:.1%}")
                
                # Attendre avant le prochain cycle
                logger.info(f"\n⏳ Attente de {self.config['check_interval']} secondes...")
                time.sleep(self.config['check_interval'])
                
        except KeyboardInterrupt:
            logger.info("\n⏹️  Arrêt du système demandé par l'utilisateur")
            self.stop()
        except Exception as e:
            logger.error(f"Erreur fatale: {e}", exc_info=True)
            self.stop()
    
    def stop(self):
        """Arrête le système"""
        self.is_running = False
        logger.info("Système arrêté")
        
        # Afficher le rapport final
        self.print_final_report()
    
    def print_final_report(self):
        """Affiche un rapport final de performance"""
        status = self.trading_engine.get_status()
        performance = status['performance']
        
        logger.info("\n" + "=" * 80)
        logger.info("RAPPORT FINAL DE PERFORMANCE")
        logger.info("=" * 80)
        logger.info(f"Total de trades: {performance['total_trades']}")
        logger.info(f"Trades réussis: {performance['successful_trades']}")
        logger.info(f"Trades ratés: {performance['failed_trades']}")
        logger.info(f"Taux de réussite: {performance['win_rate']:.1%}")
        logger.info(f"Profit total: {performance['total_profit']:.2f}")
        logger.info(f"Profit moyen par trade: {performance['average_profit']:.2f}")
        
        if 'best_trade' in performance:
            logger.info(f"Meilleur trade: {performance['best_trade']:.2f}")
            logger.info(f"Pire trade: {performance['worst_trade']:.2f}")
        
        risk_status = status['risk_status']
        logger.info(f"\nCapital initial: {risk_status['initial_capital']:.2f}")
        logger.info(f"Capital final: {risk_status['current_capital']:.2f}")
        logger.info(f"Retour sur investissement: {risk_status['return_percentage']:.2f}%")
        logger.info("=" * 80)
    
    def demo_mode(self, cycles: int = 10):
        """
        Mode démo pour tester le système sur un nombre limité de cycles
        
        Args:
            cycles: Nombre de cycles à exécuter
        """
        logger.info(f"🎮 Mode DEMO - Exécution de {cycles} cycles")
        
        for i in range(cycles):
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Cycle DEMO #{i+1}/{cycles}")
            logger.info(f"{'=' * 80}")
            
            self.run_single_cycle()
            
            # Optimiser à mi-parcours
            if i == cycles // 2:
                logger.info("\n🔧 Optimisation intermédiaire...")
                self.trading_engine.optimize()
            
            time.sleep(2)  # Pause courte en mode démo
        
        # Optimisation finale
        logger.info("\n🔧 Optimisation finale...")
        optimization_result = self.trading_engine.optimize()
        
        # Rapport final
        self.print_final_report()


def main():
    """Point d'entrée principal"""
    # Configuration personnalisée
    config = {
        'symbol': 'BTC-USD',
        'interval': '1h',
        'period': '3mo',
        'initial_capital': 10000,
        'max_risk_per_trade': 0.02,
        'max_daily_loss': 0.05,
        'min_confidence': 0.6,
        'demo_mode': True,
        'optimization_interval': 10,
        'check_interval': 60
    }
    
    app = TradingApplication(config)
    
    # Choisir le mode
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'demo':
        cycles = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        app.demo_mode(cycles)
    else:
        app.run_continuous()


if __name__ == '__main__':
    main()
