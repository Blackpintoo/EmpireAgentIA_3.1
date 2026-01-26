# utils/market_regime.py
"""
OUTIL 2: Market Regime Detector (OPTIMISATION 2025-12-13)

Détecte le régime de marché actuel pour adapter la stratégie:
1. TRENDING_UP - Tendance haussière forte
2. TRENDING_DOWN - Tendance baissière forte
3. RANGING - Marché en range/consolidation
4. VOLATILE - Haute volatilité sans direction claire
5. QUIET - Faible volatilité, peu d'opportunités

Indicateurs utilisés:
- ADX (Average Directional Index) - Force de la tendance
- Bollinger Band Width - Expansion/Contraction de la volatilité
- ATR Percentile - Position de la volatilité actuelle vs historique
- Price Position vs EMA - Direction de la tendance

Objectif: Adapter la stratégie au régime (trend-following vs mean-reversion)
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

import pandas as pd
import numpy as np

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Types de régimes de marché"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"
    UNKNOWN = "unknown"


@dataclass
class RegimeConfig:
    """Configuration du détecteur de régime"""
    # ADX
    adx_period: int = 14
    adx_trend_threshold: float = 25.0      # ADX > 25 = tendance
    adx_strong_trend: float = 40.0         # ADX > 40 = tendance forte

    # Bollinger
    bb_period: int = 20
    bb_std: float = 2.0
    bb_squeeze_threshold: float = 0.02     # BB Width < 2% = squeeze
    bb_expansion_threshold: float = 0.05   # BB Width > 5% = expansion

    # ATR
    atr_period: int = 14
    atr_lookback: int = 100                # Périodes pour le percentile
    atr_high_percentile: float = 80        # ATR > 80e percentile = volatile
    atr_low_percentile: float = 20         # ATR < 20e percentile = quiet

    # EMA
    ema_fast: int = 20
    ema_slow: int = 50

    # Regime persistence
    min_bars_for_regime: int = 5           # Minimum de bougies pour confirmer


class MarketRegimeDetector:
    """
    Détecteur de régime de marché.

    Analyse plusieurs indicateurs pour déterminer si le marché est:
    - En tendance (UP/DOWN)
    - En range
    - Volatile
    - Calme
    """

    def __init__(self, symbol: str, config: Optional[RegimeConfig] = None):
        self.symbol = symbol.upper()
        self.config = config or RegimeConfig()

        # Cache
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        self._regime_confidence: float = 0.0
        self._regime_since: Optional[datetime] = None
        self._regime_bars: int = 0

    def _calculate_adx(self, df: pd.DataFrame) -> Tuple[float, float, float]:
        """
        Calcule l'ADX et les DI+/DI-.

        Returns:
            Tuple[adx, di_plus, di_minus]
        """
        if len(df) < self.config.adx_period + 1:
            return 0.0, 0.0, 0.0

        try:
            high = df['high']
            low = df['low']
            close = df['close']

            # True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=self.config.adx_period).mean()

            # Directional Movement
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low

            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

            plus_dm = pd.Series(plus_dm, index=df.index)
            minus_dm = pd.Series(minus_dm, index=df.index)

            # Smoothed DM
            plus_dm_smooth = plus_dm.rolling(window=self.config.adx_period).mean()
            minus_dm_smooth = minus_dm.rolling(window=self.config.adx_period).mean()

            # DI+ et DI-
            di_plus = 100 * plus_dm_smooth / atr.replace(0, np.nan)
            di_minus = 100 * minus_dm_smooth / atr.replace(0, np.nan)

            # DX et ADX
            dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus).replace(0, np.nan)
            adx = dx.rolling(window=self.config.adx_period).mean()

            return (
                float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0,
                float(di_plus.iloc[-1]) if not pd.isna(di_plus.iloc[-1]) else 0.0,
                float(di_minus.iloc[-1]) if not pd.isna(di_minus.iloc[-1]) else 0.0
            )

        except Exception as e:
            logger.debug(f"[REGIME] Erreur calcul ADX: {e}")
            return 0.0, 0.0, 0.0

    def _calculate_bollinger_width(self, df: pd.DataFrame) -> float:
        """
        Calcule la largeur des bandes de Bollinger (normalized).

        Returns:
            BB Width en pourcentage du prix
        """
        if len(df) < self.config.bb_period:
            return 0.0

        try:
            close = df['close']
            sma = close.rolling(window=self.config.bb_period).mean()
            std = close.rolling(window=self.config.bb_period).std()

            upper = sma + self.config.bb_std * std
            lower = sma - self.config.bb_std * std

            # Width normalisé par le prix
            width = (upper - lower) / sma

            return float(width.iloc[-1]) if not pd.isna(width.iloc[-1]) else 0.0

        except Exception as e:
            logger.debug(f"[REGIME] Erreur calcul BB Width: {e}")
            return 0.0

    def _calculate_atr_percentile(self, df: pd.DataFrame) -> float:
        """
        Calcule le percentile de l'ATR actuel vs historique.

        Returns:
            Percentile (0-100)
        """
        if len(df) < self.config.atr_lookback:
            return 50.0

        try:
            high = df['high']
            low = df['low']
            close = df['close']

            tr = pd.concat([
                high - low,
                abs(high - close.shift(1)),
                abs(low - close.shift(1))
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=self.config.atr_period).mean()
            current_atr = atr.iloc[-1]

            # Calculer le percentile
            historical_atr = atr.iloc[-self.config.atr_lookback:]
            percentile = (historical_atr < current_atr).sum() / len(historical_atr) * 100

            return float(percentile)

        except Exception as e:
            logger.debug(f"[REGIME] Erreur calcul ATR percentile: {e}")
            return 50.0

    def _calculate_trend_direction(self, df: pd.DataFrame) -> Tuple[str, float]:
        """
        Détermine la direction de la tendance via EMA.

        Returns:
            Tuple[direction, strength] - direction: "up"/"down"/"neutral", strength: 0-1
        """
        if len(df) < self.config.ema_slow:
            return "neutral", 0.0

        try:
            close = df['close']
            ema_fast = close.ewm(span=self.config.ema_fast, adjust=False).mean()
            ema_slow = close.ewm(span=self.config.ema_slow, adjust=False).mean()

            current_price = close.iloc[-1]
            fast = ema_fast.iloc[-1]
            slow = ema_slow.iloc[-1]

            # Direction
            if fast > slow and current_price > fast:
                direction = "up"
            elif fast < slow and current_price < fast:
                direction = "down"
            else:
                direction = "neutral"

            # Force de la tendance (distance entre EMAs normalisée)
            ema_spread = abs(fast - slow) / slow
            strength = min(ema_spread * 20, 1.0)  # Normaliser à 0-1

            return direction, float(strength)

        except Exception as e:
            logger.debug(f"[REGIME] Erreur calcul direction: {e}")
            return "neutral", 0.0

    def detect_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Détecte le régime de marché actuel.

        Args:
            df: DataFrame avec colonnes OHLCV

        Returns:
            Dict avec regime, confidence, metrics
        """
        result = {
            "regime": MarketRegime.UNKNOWN,
            "regime_name": "unknown",
            "confidence": 0.0,
            "adx": 0.0,
            "di_plus": 0.0,
            "di_minus": 0.0,
            "bb_width": 0.0,
            "atr_percentile": 50.0,
            "trend_direction": "neutral",
            "trend_strength": 0.0,
            "recommended_strategy": "wait"
        }

        if df is None or len(df) < max(self.config.ema_slow, self.config.atr_lookback):
            return result

        try:
            # Calculer les indicateurs
            adx, di_plus, di_minus = self._calculate_adx(df)
            bb_width = self._calculate_bollinger_width(df)
            atr_percentile = self._calculate_atr_percentile(df)
            trend_dir, trend_strength = self._calculate_trend_direction(df)

            result["adx"] = adx
            result["di_plus"] = di_plus
            result["di_minus"] = di_minus
            result["bb_width"] = bb_width
            result["atr_percentile"] = atr_percentile
            result["trend_direction"] = trend_dir
            result["trend_strength"] = trend_strength

            # Déterminer le régime
            regime = MarketRegime.UNKNOWN
            confidence = 0.0

            # 1. Vérifier si VOLATILE (haute volatilité sans direction)
            if atr_percentile > self.config.atr_high_percentile and adx < self.config.adx_trend_threshold:
                regime = MarketRegime.VOLATILE
                confidence = 0.6 + (atr_percentile - self.config.atr_high_percentile) / 100

            # 2. Vérifier si QUIET (faible volatilité)
            elif atr_percentile < self.config.atr_low_percentile or bb_width < self.config.bb_squeeze_threshold:
                regime = MarketRegime.QUIET
                confidence = 0.5 + (self.config.atr_low_percentile - atr_percentile) / 100

            # 3. Vérifier si TRENDING (ADX fort + direction claire)
            elif adx >= self.config.adx_trend_threshold:
                if di_plus > di_minus and trend_dir == "up":
                    regime = MarketRegime.TRENDING_UP
                    confidence = 0.5 + (adx - self.config.adx_trend_threshold) / 50 + trend_strength * 0.2
                elif di_minus > di_plus and trend_dir == "down":
                    regime = MarketRegime.TRENDING_DOWN
                    confidence = 0.5 + (adx - self.config.adx_trend_threshold) / 50 + trend_strength * 0.2
                else:
                    regime = MarketRegime.RANGING
                    confidence = 0.4

            # 4. Par défaut: RANGING
            else:
                regime = MarketRegime.RANGING
                confidence = 0.4 + (self.config.adx_trend_threshold - adx) / 50

            # Limiter la confiance
            confidence = min(max(confidence, 0.0), 1.0)

            result["regime"] = regime
            result["regime_name"] = regime.value
            result["confidence"] = confidence

            # Stratégie recommandée
            if regime == MarketRegime.TRENDING_UP:
                result["recommended_strategy"] = "trend_following_long"
                result["avoid_shorts"] = True
            elif regime == MarketRegime.TRENDING_DOWN:
                result["recommended_strategy"] = "trend_following_short"
                result["avoid_longs"] = True
            elif regime == MarketRegime.RANGING:
                result["recommended_strategy"] = "mean_reversion"
                result["use_tight_stops"] = True
            elif regime == MarketRegime.VOLATILE:
                result["recommended_strategy"] = "reduce_size"
                result["widen_stops"] = True
            elif regime == MarketRegime.QUIET:
                result["recommended_strategy"] = "wait_for_breakout"
                result["reduce_trading"] = True

            # Mettre à jour le cache
            if regime != self._current_regime:
                self._current_regime = regime
                self._regime_since = datetime.now(timezone.utc)
                self._regime_bars = 1
            else:
                self._regime_bars += 1

            result["regime_bars"] = self._regime_bars
            result["regime_stable"] = self._regime_bars >= self.config.min_bars_for_regime

            return result

        except Exception as e:
            logger.error(f"[REGIME] Erreur détection: {e}")
            return result

    def should_allow_trade(self, direction: str, regime_result: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Vérifie si un trade est permis selon le régime actuel.

        Args:
            direction: "LONG" ou "SHORT"
            regime_result: Résultat de detect_regime()

        Returns:
            Tuple[allowed, reason]
        """
        regime = regime_result.get("regime", MarketRegime.UNKNOWN)
        confidence = regime_result.get("confidence", 0.0)

        # Régime instable: ne pas trader
        if not regime_result.get("regime_stable", False):
            return False, "regime_unstable"

        # Faible confiance
        if confidence < 0.4:
            return False, "low_regime_confidence"

        direction = direction.upper()

        # VOLATILE: réduire le trading
        if regime == MarketRegime.VOLATILE:
            if confidence > 0.7:
                return False, "high_volatility"
            return True, "volatile_ok_reduced"

        # QUIET: éviter le trading
        if regime == MarketRegime.QUIET:
            return False, "low_volatility_wait"

        # TRENDING_UP: éviter les shorts
        if regime == MarketRegime.TRENDING_UP and direction == "SHORT":
            return False, "against_uptrend"

        # TRENDING_DOWN: éviter les longs
        if regime == MarketRegime.TRENDING_DOWN and direction == "LONG":
            return False, "against_downtrend"

        return True, "regime_ok"


# Instance globale par symbole
_regime_detectors: Dict[str, MarketRegimeDetector] = {}


def get_regime_detector(symbol: str, config: Optional[RegimeConfig] = None) -> MarketRegimeDetector:
    """Récupère ou crée un détecteur de régime pour un symbole"""
    global _regime_detectors

    symbol = symbol.upper()
    if symbol not in _regime_detectors:
        _regime_detectors[symbol] = MarketRegimeDetector(symbol, config)

    return _regime_detectors[symbol]


def detect_market_regime(symbol: str, df: pd.DataFrame, config: Optional[RegimeConfig] = None) -> Dict[str, Any]:
    """
    Fonction utilitaire pour détecter le régime de marché.

    Args:
        symbol: Symbole à analyser
        df: DataFrame OHLCV
        config: Configuration optionnelle

    Returns:
        Dict avec regime, confidence, metrics, recommendations
    """
    detector = get_regime_detector(symbol, config)
    return detector.detect_regime(df)
