"""
Récupération des données de marché
Utilise yfinance pour obtenir les données historiques et en temps réel
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """
    Récupère les données de marché depuis différentes sources
    """
    
    def __init__(self):
        self.cache = {}
        logger.info("MarketDataFetcher initialisé")
    
    def fetch_data(self, symbol: str, period: str = '1mo', interval: str = '1h') -> pd.DataFrame:
        """
        Récupère les données de marché pour un symbole
        
        Args:
            symbol: Symbole du marché (ex: 'BTC-USD', 'AAPL', 'EURUSD=X')
            period: Période de données ('1d', '5d', '1mo', '3mo', '1y', etc.)
            interval: Intervalle ('1m', '5m', '15m', '1h', '1d')
            
        Returns:
            DataFrame avec colonnes: open, high, low, close, volume
        """
        logger.info(f"Récupération des données pour {symbol} (période: {period}, intervalle: {interval})")
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                logger.error(f"Aucune donnée reçue pour {symbol}")
                return None
            
            # Normaliser les noms de colonnes
            df.columns = df.columns.str.lower()
            
            # Supprimer les lignes avec des valeurs manquantes
            df = df.dropna()
            
            logger.info(f"Données récupérées: {len(df)} périodes")
            
            return df
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des données pour {symbol}: {e}")
            return None
    
    def get_realtime_price(self, symbol: str) -> float:
        """
        Obtient le prix actuel d'un symbole
        
        Args:
            symbol: Symbole du marché
            
        Returns:
            Prix actuel ou None si erreur
        """
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='1d', interval='1m')
            
            if not data.empty:
                return data['Close'].iloc[-1]
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du prix pour {symbol}: {e}")
            return None
    
    def fetch_multiple_symbols(self, symbols: list, period: str = '1mo', interval: str = '1h') -> dict:
        """
        Récupère les données pour plusieurs symboles
        
        Args:
            symbols: Liste des symboles
            period: Période de données
            interval: Intervalle
            
        Returns:
            Dict avec symbole -> DataFrame
        """
        data = {}
        
        for symbol in symbols:
            df = self.fetch_data(symbol, period, interval)
            if df is not None:
                data[symbol] = df
        
        return data
