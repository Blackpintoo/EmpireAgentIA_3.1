# utils/inter_market_guard.py
"""
INTER-MARKET GUARD - Blocage basé sur les corrélations inter-marchés
(PHASE 4 - Amélioration 2025-12-17)

Fonctionnalités:
1. Analyse rapide des flux macro (DXY, Gold, SPX)
2. Blocage si trade contre le flux dominant
3. Cache des analyses pour performance
4. Intégration avec MT5 pour récupérer les données

Objectif: Ne pas trader contre les flux macro dominants.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import threading

import pandas as pd
import numpy as np

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.inter_market_correlation import (
        analyze_inter_market_correlation,
        get_correlation_analyzer,
        InterMarketCorrelationAnalyzer
    )
    INTER_MARKET_AVAILABLE = True
except ImportError:
    INTER_MARKET_AVAILABLE = False
    logger.warning("[IM_GUARD] inter_market_correlation non disponible")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class InterMarketGuardConfig:
    """Configuration du garde inter-marchés"""
    enabled: bool = True

    # Seuils de blocage
    min_confidence_to_block: float = 0.5   # Confiance minimum pour bloquer

    # Marchés de référence par symbole
    reference_markets: Dict[str, List[str]] = field(default_factory=lambda: {
        # Forex vs DXY
        "EURUSD": ["DXY"],
        "GBPUSD": ["DXY"],
        "AUDUSD": ["DXY", "SPX500"],
        "USDJPY": ["SPX500"],
        "USDCAD": ["USOIL"],

        # Commodities
        "XAUUSD": ["DXY"],
        "XAGUSD": ["XAUUSD", "DXY"],
        "USOUSD": ["DXY"],

        # Crypto
        "BTCUSD": ["ETHUSD", "SPX500"],
        "ETHUSD": ["BTCUSD"],
        "SOLUSD": ["BTCUSD", "ETHUSD"],
        "ADAUSD": ["BTCUSD", "ETHUSD"],

        # Indices
        "SP500": ["DXY"],
        "UK100": ["SPX500"],
    })

    # Cache
    cache_ttl_minutes: int = 15

    # MT5 timeframes
    analysis_timeframe: str = "H1"
    analysis_bars: int = 100


# =============================================================================
# INTER-MARKET GUARD
# =============================================================================

class InterMarketGuard:
    """
    Garde inter-marchés pour bloquer les trades contre les flux macro.
    """

    def __init__(
        self,
        config: Optional[InterMarketGuardConfig] = None,
        mt5=None
    ):
        self.config = config or InterMarketGuardConfig()
        self.mt5 = mt5

        # Cache des analyses
        self._analysis_cache: Dict[str, Tuple[Dict, datetime]] = {}
        self._lock = threading.Lock()

        logger.info(f"[IM_GUARD] Initialisé, enabled={self.config.enabled}")

    def _get_mt5_data(self, symbol: str, bars: int = 100) -> Optional[pd.DataFrame]:
        """Récupère les données OHLCV depuis MT5"""
        if self.mt5 is None:
            return None

        try:
            # Timeframe H1
            tf_map = {
                "M1": 1, "M5": 5, "M15": 15, "M30": 30,
                "H1": 16385, "H4": 16388, "D1": 16408
            }
            tf_val = tf_map.get(self.config.analysis_timeframe, 16385)

            rates = self.mt5.copy_rates_from_pos(symbol, tf_val, 0, bars)
            if rates is None or len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df

        except Exception as e:
            logger.debug(f"[IM_GUARD] Erreur récupération données {symbol}: {e}")
            return None

    def _is_cache_valid(self, symbol: str) -> bool:
        """Vérifie si le cache est valide pour un symbole"""
        if symbol not in self._analysis_cache:
            return False

        _, timestamp = self._analysis_cache[symbol]
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        return age < self.config.cache_ttl_minutes * 60

    def analyze(self, symbol: str) -> Dict[str, Any]:
        """
        Analyse les corrélations inter-marchés pour un symbole.

        Returns:
            Dict avec bias, should_avoid_long, should_avoid_short, etc.
        """
        if not self.config.enabled or not INTER_MARKET_AVAILABLE:
            return {
                "symbol": symbol,
                "bias": "neutral",
                "should_avoid_long": False,
                "should_avoid_short": False,
                "confidence": 0.0,
                "reason": "disabled"
            }

        # Vérifier le cache
        with self._lock:
            if self._is_cache_valid(symbol):
                return self._analysis_cache[symbol][0]

        try:
            # Récupérer les marchés de référence
            reference_symbols = self.config.reference_markets.get(
                symbol.upper(), []
            )

            if not reference_symbols:
                return {
                    "symbol": symbol,
                    "bias": "neutral",
                    "should_avoid_long": False,
                    "should_avoid_short": False,
                    "confidence": 0.0,
                    "reason": "no_reference_markets"
                }

            # Récupérer les données
            symbol_df = self._get_mt5_data(symbol, self.config.analysis_bars)

            related_dfs = {}
            for ref_sym in reference_symbols:
                df = self._get_mt5_data(ref_sym, self.config.analysis_bars)
                if df is not None:
                    related_dfs[ref_sym] = df

            if symbol_df is None or not related_dfs:
                return {
                    "symbol": symbol,
                    "bias": "neutral",
                    "should_avoid_long": False,
                    "should_avoid_short": False,
                    "confidence": 0.0,
                    "reason": "no_data"
                }

            # Analyser avec l'analyseur de corrélation
            analysis = analyze_inter_market_correlation(
                symbol=symbol,
                symbol_df=symbol_df,
                related_dfs=related_dfs
            )

            result = {
                "symbol": symbol,
                "bias": analysis.get("overall_bias", "neutral"),
                "should_avoid_long": analysis.get("should_avoid_long", False),
                "should_avoid_short": analysis.get("should_avoid_short", False),
                "confidence": analysis.get("confidence", 0.0),
                "macro_flow": analysis.get("macro_flow", "unclear"),
                "divergences": analysis.get("divergences", []),
                "correlations": analysis.get("correlations", [])[:3],
                "reason": "analyzed"
            }

            # Mettre en cache
            with self._lock:
                self._analysis_cache[symbol] = (result, datetime.now(timezone.utc))

            return result

        except Exception as e:
            logger.warning(f"[IM_GUARD] Erreur analyse {symbol}: {e}")
            return {
                "symbol": symbol,
                "bias": "neutral",
                "should_avoid_long": False,
                "should_avoid_short": False,
                "confidence": 0.0,
                "reason": f"error: {e}"
            }

    def should_allow_trade(
        self,
        symbol: str,
        direction: str
    ) -> Tuple[bool, str, float]:
        """
        Vérifie si un trade est autorisé selon l'analyse inter-marchés.

        Args:
            symbol: Symbole à trader
            direction: "LONG" ou "SHORT"

        Returns:
            Tuple[allowed, reason, confidence]
        """
        if not self.config.enabled:
            return True, "inter_market_disabled", 0.0

        analysis = self.analyze(symbol)

        confidence = analysis.get("confidence", 0.0)
        direction = direction.upper()

        # Si pas assez de confiance, autoriser par défaut
        if confidence < self.config.min_confidence_to_block:
            return True, "insufficient_confidence", confidence

        # Vérifier les blocages
        if direction == "LONG" and analysis.get("should_avoid_long", False):
            return False, f"macro_bearish_{analysis.get('bias')}", confidence

        if direction == "SHORT" and analysis.get("should_avoid_short", False):
            return False, f"macro_bullish_{analysis.get('bias')}", confidence

        # Trade aligné ou neutre
        if analysis.get("bias") == "bullish" and direction == "LONG":
            return True, "macro_aligned_bullish", confidence

        if analysis.get("bias") == "bearish" and direction == "SHORT":
            return True, "macro_aligned_bearish", confidence

        return True, "no_macro_conflict", confidence

    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut du garde"""
        return {
            "enabled": self.config.enabled,
            "cached_symbols": list(self._analysis_cache.keys()),
            "cache_entries": len(self._analysis_cache),
            "mt5_connected": self.mt5 is not None
        }


# =============================================================================
# INSTANCE GLOBALE ET FONCTIONS UTILITAIRES
# =============================================================================

_im_guard: Optional[InterMarketGuard] = None


def get_inter_market_guard(
    config: Optional[InterMarketGuardConfig] = None,
    mt5=None
) -> InterMarketGuard:
    """Récupère ou crée l'instance globale du garde inter-marchés"""
    global _im_guard

    if _im_guard is None:
        _im_guard = InterMarketGuard(config, mt5)

    return _im_guard


def is_trade_blocked_by_inter_market(
    symbol: str,
    direction: str,
    mt5=None
) -> Tuple[bool, str]:
    """
    Fonction utilitaire rapide pour vérifier si un trade est bloqué.

    Returns:
        Tuple[is_blocked, reason]
    """
    guard = get_inter_market_guard(mt5=mt5)
    allowed, reason, confidence = guard.should_allow_trade(symbol, direction)
    return not allowed, f"{reason} (conf={confidence:.2f})"


def analyze_inter_market_quick(symbol: str, mt5=None) -> Dict[str, Any]:
    """Analyse rapide inter-marchés pour un symbole"""
    guard = get_inter_market_guard(mt5=mt5)
    return guard.analyze(symbol)
