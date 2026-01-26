# utils/atr.py
"""
Module ATR (Average True Range) - Wrapper pour compatibilité.
Les fonctions ATR principales sont dans utils/indicators.py
"""

from utils.indicators import compute_atr

# Re-export pour compatibilité
__all__ = ['compute_atr', 'calculate_atr']


def calculate_atr(df, period: int = 14):
    """
    Alias pour compute_atr.

    Args:
        df: DataFrame avec colonnes high, low, close
        period: Période ATR (défaut 14)

    Returns:
        Série ATR ou None si erreur
    """
    return compute_atr(df, period)
