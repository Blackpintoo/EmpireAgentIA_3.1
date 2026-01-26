# utils/risk_sizing.py
"""
Module Risk Sizing - Wrapper pour compatibilité.
La logique principale est dans utils/risk_manager.py
"""

from typing import Optional, Dict, Any
from utils.risk_manager import RiskManager

# Re-export pour compatibilité
__all__ = ['RiskManager', 'calculate_position_size', 'get_risk_amount']


def calculate_position_size(
    equity: float,
    risk_percent: float,
    stop_distance_points: float,
    point_value: float = 1.0,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    lot_step: float = 0.01
) -> float:
    """
    Calcule la taille de position optimale basée sur le risque.

    Args:
        equity: Capital disponible
        risk_percent: Pourcentage de risque par trade (ex: 0.01 = 1%)
        stop_distance_points: Distance du stop loss en points
        point_value: Valeur d'un point
        min_lot: Lot minimum
        max_lot: Lot maximum
        lot_step: Pas de lot

    Returns:
        Taille de position en lots
    """
    if equity <= 0 or risk_percent <= 0 or stop_distance_points <= 0:
        return min_lot

    # Montant à risquer
    risk_amount = equity * risk_percent

    # Risque par lot
    risk_per_lot = stop_distance_points * point_value

    if risk_per_lot <= 0:
        return min_lot

    # Taille brute
    raw_size = risk_amount / risk_per_lot

    # Arrondir au lot_step
    if lot_step > 0:
        steps = int(raw_size / lot_step)
        raw_size = steps * lot_step

    # Clamp entre min et max
    return max(min_lot, min(raw_size, max_lot))


def get_risk_amount(equity: float, risk_percent: float) -> float:
    """
    Calcule le montant à risquer.

    Args:
        equity: Capital disponible
        risk_percent: Pourcentage de risque (ex: 0.01 = 1%)

    Returns:
        Montant en devise du compte
    """
    return equity * risk_percent if equity > 0 and risk_percent > 0 else 0.0
