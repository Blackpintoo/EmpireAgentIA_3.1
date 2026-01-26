# utils/volatility_filter.py
"""
SOLUTION 4: Filtre de volatilité avancé (OPTIMISATION 2025-12-13)

Ce module filtre les trades pendant:
1. Pics de volatilité anormale (ATR > 2x moyenne)
2. Annonces économiques majeures (via calendrier Finnhub)
3. Gaps de prix importants
4. Sessions de faible liquidité

Objectif: Éviter les trades dans des conditions de marché défavorables.
"""

from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class VolatilityConfig:
    """Configuration du filtre de volatilité"""
    # ATR Filter
    atr_spike_threshold: float = 2.0      # ATR > 2x moyenne = spike
    atr_lookback_periods: int = 20        # Périodes pour calculer la moyenne ATR

    # Spread Filter
    max_spread_atr_ratio: float = 0.3     # Spread max = 30% de l'ATR

    # Gap Filter
    gap_threshold_atr: float = 0.5        # Gap > 0.5 ATR = dangereux

    # Session Filter (heures à éviter - UTC)
    avoid_hours_utc: list = None          # Heures de faible liquidité

    # News Filter
    news_blackout_minutes: int = 30       # Éviter 30 min avant/après news

    # Momentum Filter
    momentum_min: float = 0.0             # Momentum minimum requis
    momentum_max: float = 100.0           # Momentum max (éviter les excès)

    def __post_init__(self):
        if self.avoid_hours_utc is None:
            # Éviter 22h-6h UTC (faible liquidité asie/pacifique pour forex)
            self.avoid_hours_utc = [22, 23, 0, 1, 2, 3, 4, 5]


class VolatilityFilter:
    """
    Filtre de volatilité pour bloquer les trades dans des conditions défavorables.
    """

    def __init__(self, symbol: str, config: Optional[VolatilityConfig] = None):
        self.symbol = symbol
        self.config = config or VolatilityConfig()
        self._atr_history: list = []
        self._last_check_ts: float = 0
        self._cache_ttl: float = 60  # Cache 60 secondes
        self._cached_result: Optional[Tuple[bool, str]] = None

    def update_atr(self, current_atr: float) -> None:
        """Met à jour l'historique ATR"""
        self._atr_history.append(current_atr)
        # Garder seulement les N dernières valeurs
        if len(self._atr_history) > self.config.atr_lookback_periods * 2:
            self._atr_history = self._atr_history[-self.config.atr_lookback_periods:]

    def get_atr_ratio(self, current_atr: float) -> float:
        """Calcule le ratio ATR actuel / moyenne ATR"""
        if len(self._atr_history) < 5:
            return 1.0  # Pas assez de données

        avg_atr = sum(self._atr_history[-self.config.atr_lookback_periods:]) / min(
            len(self._atr_history), self.config.atr_lookback_periods
        )

        if avg_atr <= 0:
            return 1.0

        return current_atr / avg_atr

    def is_atr_spike(self, current_atr: float) -> bool:
        """Vérifie si l'ATR actuel est un spike"""
        ratio = self.get_atr_ratio(current_atr)
        return ratio > self.config.atr_spike_threshold

    def is_spread_acceptable(self, spread: float, atr: float) -> bool:
        """Vérifie si le spread est acceptable par rapport à l'ATR"""
        if atr <= 0:
            return True
        ratio = spread / atr
        return ratio <= self.config.max_spread_atr_ratio

    def is_gap_safe(self, gap_size: float, atr: float) -> bool:
        """Vérifie si le gap de prix est dans les limites"""
        if atr <= 0:
            return True
        ratio = abs(gap_size) / atr
        return ratio <= self.config.gap_threshold_atr

    def is_session_active(self) -> Tuple[bool, str]:
        """Vérifie si la session actuelle est favorable"""
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        if current_hour in self.config.avoid_hours_utc:
            return False, f"low_liquidity_hour_{current_hour}UTC"

        return True, "session_ok"

    def check_all_filters(
        self,
        current_atr: float,
        spread: Optional[float] = None,
        gap_size: Optional[float] = None,
        has_news_event: bool = False,
        momentum: Optional[float] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Vérifie tous les filtres de volatilité.

        Returns:
            Tuple[bool, str, Dict]: (allowed, reason, metrics)
        """
        metrics = {
            "atr": current_atr,
            "atr_ratio": self.get_atr_ratio(current_atr),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Mise à jour de l'historique ATR
        self.update_atr(current_atr)

        # 1. Vérifier le spike ATR
        if self.is_atr_spike(current_atr):
            metrics["filter_triggered"] = "atr_spike"
            metrics["atr_threshold"] = self.config.atr_spike_threshold
            return False, f"atr_spike_detected (ratio={metrics['atr_ratio']:.2f})", metrics

        # 2. Vérifier le spread
        if spread is not None and not self.is_spread_acceptable(spread, current_atr):
            spread_ratio = spread / current_atr if current_atr > 0 else 0
            metrics["spread_ratio"] = spread_ratio
            metrics["filter_triggered"] = "spread_too_high"
            return False, f"spread_too_high (ratio={spread_ratio:.2f})", metrics

        # 3. Vérifier le gap
        if gap_size is not None and not self.is_gap_safe(gap_size, current_atr):
            gap_ratio = abs(gap_size) / current_atr if current_atr > 0 else 0
            metrics["gap_ratio"] = gap_ratio
            metrics["filter_triggered"] = "gap_too_large"
            return False, f"gap_too_large (ratio={gap_ratio:.2f})", metrics

        # 4. Vérifier la session
        session_ok, session_msg = self.is_session_active()
        if not session_ok:
            metrics["filter_triggered"] = "session"
            return False, session_msg, metrics

        # 5. Vérifier les news
        if has_news_event:
            metrics["filter_triggered"] = "news_blackout"
            return False, "news_blackout_active", metrics

        # 6. Vérifier le momentum
        if momentum is not None:
            if momentum < self.config.momentum_min:
                metrics["filter_triggered"] = "low_momentum"
                return False, f"momentum_too_low ({momentum:.2f})", metrics
            if momentum > self.config.momentum_max:
                metrics["filter_triggered"] = "extreme_momentum"
                return False, f"momentum_extreme ({momentum:.2f})", metrics

        # Tous les filtres passés
        metrics["filter_triggered"] = None
        return True, "volatility_ok", metrics


# Cache global des filtres par symbole
_volatility_filters: Dict[str, VolatilityFilter] = {}


def get_volatility_filter(symbol: str, config: Optional[VolatilityConfig] = None) -> VolatilityFilter:
    """Récupère ou crée un filtre de volatilité pour un symbole"""
    global _volatility_filters

    if symbol not in _volatility_filters:
        _volatility_filters[symbol] = VolatilityFilter(symbol, config)

    return _volatility_filters[symbol]


def should_trade_volatility(
    symbol: str,
    current_atr: float,
    spread: Optional[float] = None,
    gap_size: Optional[float] = None,
    has_news_event: bool = False,
    momentum: Optional[float] = None,
    config: Optional[VolatilityConfig] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Fonction utilitaire pour vérifier si on peut trader selon la volatilité.

    Args:
        symbol: Symbole à vérifier
        current_atr: ATR actuel
        spread: Spread actuel (optionnel)
        gap_size: Taille du gap depuis la dernière bougie (optionnel)
        has_news_event: True si un événement news est proche
        momentum: Valeur du momentum (optionnel)
        config: Configuration personnalisée (optionnel)

    Returns:
        Tuple[bool, str, Dict]: (allowed, reason, metrics)
    """
    vf = get_volatility_filter(symbol, config)
    return vf.check_all_filters(
        current_atr=current_atr,
        spread=spread,
        gap_size=gap_size,
        has_news_event=has_news_event,
        momentum=momentum
    )


# Configuration par type d'actif
ASSET_VOLATILITY_CONFIGS = {
    "crypto": VolatilityConfig(
        atr_spike_threshold=2.5,      # Crypto plus volatile, seuil plus haut
        max_spread_atr_ratio=0.4,     # Spreads plus larges acceptés
        avoid_hours_utc=[],           # Crypto 24/7
        momentum_max=150.0            # Mouvements plus extrêmes OK
    ),
    "forex": VolatilityConfig(
        atr_spike_threshold=2.0,
        max_spread_atr_ratio=0.25,
        avoid_hours_utc=[22, 23, 0, 1, 2, 3, 4, 5],  # Éviter Asie pour majors
        news_blackout_minutes=45      # Plus de temps avant/après news
    ),
    "commodities": VolatilityConfig(
        atr_spike_threshold=1.8,      # Or/Argent sensibles
        max_spread_atr_ratio=0.3,
        avoid_hours_utc=[22, 23, 0, 1, 2, 3],
        news_blackout_minutes=60      # 1h autour des news
    ),
    "indices": VolatilityConfig(
        atr_spike_threshold=2.0,
        max_spread_atr_ratio=0.35,
        avoid_hours_utc=[21, 22, 23, 0, 1, 2, 3, 4, 5, 6],  # Hors heures marché
        news_blackout_minutes=30
    )
}


def get_config_for_asset_type(asset_type: str) -> VolatilityConfig:
    """Récupère la config de volatilité pour un type d'actif"""
    return ASSET_VOLATILITY_CONFIGS.get(asset_type.lower(), VolatilityConfig())
