# utils/inter_market_correlation.py
"""
OUTIL 5: Inter-Market Correlation Analyzer (OPTIMISATION 2025-12-13)

Analyse les corrélations entre marchés liés pour:
1. Confirmer/Invalider les signaux de trading
2. Détecter les divergences inter-marchés (opportunités)
3. Éviter les trades contre les flux macro

Corrélations analysées:
- DXY (Dollar Index) vs EUR/USD, GBP/USD, AUD/USD (corrélation négative)
- Gold (XAU/USD) vs USD, vs SPX (flight to safety)
- Oil vs CAD (corrélation positive - Canada exportateur)
- BTC vs ETH vs Altcoins (corrélation crypto)
- Indices vs Risk-on currencies (AUD, NZD)

Objectif: Ne pas trader contre les flux macro dominants.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
import os

import pandas as pd
import numpy as np

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class CorrelationType(Enum):
    """Type de corrélation entre marchés"""
    POSITIVE = "positive"      # Se déplacent ensemble
    NEGATIVE = "negative"      # Se déplacent inversement
    DYNAMIC = "dynamic"        # Varie selon le contexte


@dataclass
class MarketPair:
    """Paire de marchés corrélés"""
    primary: str               # Marché primaire (driver)
    secondary: str             # Marché secondaire (follower)
    correlation_type: CorrelationType
    expected_correlation: float  # Corrélation attendue (-1 à 1)
    weight: float = 1.0        # Importance de cette relation
    description: str = ""


@dataclass
class InterMarketConfig:
    """Configuration de l'analyseur inter-marchés"""
    # Périodes de calcul
    correlation_period: int = 20        # Bougies pour calculer la corrélation
    lookback_bars: int = 100            # Historique pour l'analyse

    # Seuils
    strong_correlation_threshold: float = 0.7   # Corrélation forte
    weak_correlation_threshold: float = 0.3     # Corrélation faible
    divergence_threshold: float = 0.4           # Seuil de divergence

    # Cache
    cache_ttl_minutes: int = 30
    cache_dir: str = "data/correlation_cache"

    # Relations de marché prédéfinies
    market_pairs: List[MarketPair] = field(default_factory=list)

    def __post_init__(self):
        if not self.market_pairs:
            self.market_pairs = self._default_market_pairs()

    def _default_market_pairs(self) -> List[MarketPair]:
        """Relations de marché par défaut"""
        return [
            # DXY vs Majors (corrélation négative)
            MarketPair("DXY", "EURUSD", CorrelationType.NEGATIVE, -0.85, 1.0,
                      "EUR/USD inversement corrélé au Dollar Index"),
            MarketPair("DXY", "GBPUSD", CorrelationType.NEGATIVE, -0.80, 0.9,
                      "GBP/USD inversement corrélé au Dollar Index"),
            MarketPair("DXY", "AUDUSD", CorrelationType.NEGATIVE, -0.75, 0.8,
                      "AUD/USD inversement corrélé au Dollar Index"),

            # Gold relations
            MarketPair("XAUUSD", "DXY", CorrelationType.NEGATIVE, -0.70, 1.0,
                      "Or inversement corrélé au Dollar"),
            MarketPair("XAUUSD", "XAGUSD", CorrelationType.POSITIVE, 0.85, 0.8,
                      "Or et Argent fortement corrélés"),

            # Oil vs CAD
            MarketPair("USOIL", "USDCAD", CorrelationType.NEGATIVE, -0.65, 0.7,
                      "Pétrole impacte le CAD (Canada exportateur)"),

            # Crypto corrélations
            MarketPair("BTCUSD", "ETHUSD", CorrelationType.POSITIVE, 0.90, 1.0,
                      "BTC et ETH très corrélés"),
            MarketPair("BTCUSD", "LTCUSD", CorrelationType.POSITIVE, 0.80, 0.6,
                      "BTC et LTC corrélés"),

            # JPY safe-haven
            MarketPair("USDJPY", "SPX500", CorrelationType.POSITIVE, 0.60, 0.7,
                      "JPY faiblir quand risk-on (indices montent)"),

            # AUD risk-on
            MarketPair("AUDUSD", "SPX500", CorrelationType.POSITIVE, 0.55, 0.6,
                      "AUD corrélé aux indices (risk-on currency)"),
        ]


@dataclass
class CorrelationResult:
    """Résultat d'analyse de corrélation"""
    pair: MarketPair
    actual_correlation: float
    expected_correlation: float
    deviation: float              # Écart vs attendu
    is_diverging: bool            # Divergence détectée
    primary_trend: str            # up/down/neutral
    secondary_trend: str
    signal_implication: str       # Impact sur le signal
    confidence: float


class InterMarketCorrelationAnalyzer:
    """
    Analyseur de corrélation inter-marchés.

    Détecte les flux macro et les divergences pour confirmer
    ou invalider les signaux de trading.
    """

    def __init__(self, config: Optional[InterMarketConfig] = None):
        self.config = config or InterMarketConfig()

        # Cache des données de prix
        self._price_cache: Dict[str, pd.DataFrame] = {}
        self._correlation_cache: Dict[str, CorrelationResult] = {}
        self._last_update: Optional[datetime] = None

        # Créer le répertoire de cache
        os.makedirs(self.config.cache_dir, exist_ok=True)

        # Mapping symbole -> paires associées
        self._symbol_pairs = self._build_symbol_pairs_map()

    def _build_symbol_pairs_map(self) -> Dict[str, List[MarketPair]]:
        """Construit un mapping symbole -> paires associées"""
        result = {}
        for pair in self.config.market_pairs:
            # Ajouter pour le primaire
            if pair.primary not in result:
                result[pair.primary] = []
            result[pair.primary].append(pair)

            # Ajouter pour le secondaire
            if pair.secondary not in result:
                result[pair.secondary] = []
            result[pair.secondary].append(pair)

        return result

    def get_related_pairs(self, symbol: str) -> List[MarketPair]:
        """Récupère les paires de marché liées à un symbole"""
        symbol = symbol.upper()

        # Normaliser les variantes de symboles
        symbol_variants = {
            "XAUUSD": ["GOLD", "XAU"],
            "XAGUSD": ["SILVER", "XAG"],
            "USOIL": ["CL-OIL", "CRUDE", "WTI"],
            "SPX500": ["SP500", "US500", "SPX"],
        }

        # Chercher directement
        if symbol in self._symbol_pairs:
            return self._symbol_pairs[symbol]

        # Chercher les variantes
        for canonical, variants in symbol_variants.items():
            if symbol in variants or symbol == canonical:
                if canonical in self._symbol_pairs:
                    return self._symbol_pairs[canonical]

        return []

    def _calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """Calcule les rendements logarithmiques"""
        if df is None or len(df) < 2:
            return pd.Series()

        close = df['close']
        returns = np.log(close / close.shift(1))
        return returns.dropna()

    def _calculate_correlation(
        self,
        returns1: pd.Series,
        returns2: pd.Series
    ) -> float:
        """Calcule la corrélation de Pearson entre deux séries de rendements"""
        if len(returns1) < 10 or len(returns2) < 10:
            return 0.0

        # Aligner les séries
        aligned = pd.concat([returns1, returns2], axis=1).dropna()
        if len(aligned) < 10:
            return 0.0

        try:
            correlation = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
            return float(correlation) if not pd.isna(correlation) else 0.0
        except Exception:
            return 0.0

    def _detect_trend(self, df: pd.DataFrame, period: int = 20) -> str:
        """Détecte la tendance d'un marché"""
        if df is None or len(df) < period:
            return "neutral"

        try:
            close = df['close'].iloc[-period:]

            # EMA courte vs EMA longue
            ema_short = close.ewm(span=min(5, period//2), adjust=False).mean().iloc[-1]
            ema_long = close.ewm(span=period, adjust=False).mean().iloc[-1]

            # Variation sur la période
            change_pct = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]

            if ema_short > ema_long and change_pct > 0.005:
                return "up"
            elif ema_short < ema_long and change_pct < -0.005:
                return "down"
            else:
                return "neutral"

        except Exception:
            return "neutral"

    def analyze_pair(
        self,
        pair: MarketPair,
        primary_df: pd.DataFrame,
        secondary_df: pd.DataFrame
    ) -> CorrelationResult:
        """
        Analyse une paire de marchés corrélés.

        Args:
            pair: Définition de la paire
            primary_df: DataFrame OHLCV du marché primaire
            secondary_df: DataFrame OHLCV du marché secondaire

        Returns:
            CorrelationResult avec l'analyse complète
        """
        result = CorrelationResult(
            pair=pair,
            actual_correlation=0.0,
            expected_correlation=pair.expected_correlation,
            deviation=0.0,
            is_diverging=False,
            primary_trend="neutral",
            secondary_trend="neutral",
            signal_implication="neutral",
            confidence=0.0
        )

        if primary_df is None or secondary_df is None:
            return result

        try:
            # Calculer les rendements
            returns_primary = self._calculate_returns(primary_df)
            returns_secondary = self._calculate_returns(secondary_df)

            if len(returns_primary) < 10 or len(returns_secondary) < 10:
                return result

            # Calculer la corrélation actuelle
            actual_corr = self._calculate_correlation(returns_primary, returns_secondary)
            result.actual_correlation = actual_corr

            # Calculer la déviation par rapport à l'attendu
            result.deviation = abs(actual_corr - pair.expected_correlation)

            # Détecter les tendances
            result.primary_trend = self._detect_trend(primary_df, self.config.correlation_period)
            result.secondary_trend = self._detect_trend(secondary_df, self.config.correlation_period)

            # Détecter une divergence
            if pair.correlation_type == CorrelationType.POSITIVE:
                # Devrait bouger ensemble
                if result.primary_trend == "up" and result.secondary_trend == "down":
                    result.is_diverging = True
                elif result.primary_trend == "down" and result.secondary_trend == "up":
                    result.is_diverging = True
            elif pair.correlation_type == CorrelationType.NEGATIVE:
                # Devrait bouger inversement
                if result.primary_trend == "up" and result.secondary_trend == "up":
                    result.is_diverging = True
                elif result.primary_trend == "down" and result.secondary_trend == "down":
                    result.is_diverging = True

            # Aussi divergence si corrélation s'écarte trop de l'attendu
            if result.deviation > self.config.divergence_threshold:
                result.is_diverging = True

            # Déterminer l'implication pour le signal
            result.signal_implication = self._get_signal_implication(result, pair)

            # Confiance basée sur la force de la corrélation
            if abs(actual_corr) > self.config.strong_correlation_threshold:
                result.confidence = 0.8
            elif abs(actual_corr) > self.config.weak_correlation_threshold:
                result.confidence = 0.5
            else:
                result.confidence = 0.3

            return result

        except Exception as e:
            logger.debug(f"[INTER_MARKET] Erreur analyse paire: {e}")
            return result

    def _get_signal_implication(
        self,
        result: CorrelationResult,
        pair: MarketPair
    ) -> str:
        """Détermine l'implication du signal basé sur la corrélation"""

        if result.is_diverging:
            return "divergence_opportunity"

        # Si le primaire trend et la corrélation est forte
        if result.primary_trend == "up":
            if pair.correlation_type == CorrelationType.POSITIVE:
                return "secondary_bullish"  # Le secondaire devrait monter
            else:
                return "secondary_bearish"  # Le secondaire devrait baisser
        elif result.primary_trend == "down":
            if pair.correlation_type == CorrelationType.POSITIVE:
                return "secondary_bearish"
            else:
                return "secondary_bullish"

        return "neutral"

    def analyze_symbol(
        self,
        symbol: str,
        symbol_df: pd.DataFrame,
        related_dfs: Dict[str, pd.DataFrame]
    ) -> Dict[str, Any]:
        """
        Analyse un symbole par rapport à tous ses marchés corrélés.

        Args:
            symbol: Symbole à analyser
            symbol_df: DataFrame OHLCV du symbole
            related_dfs: Dict[symbol] -> DataFrame des marchés liés

        Returns:
            Dict avec analyse complète et recommandations
        """
        result = {
            "symbol": symbol.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlations": [],
            "overall_bias": "neutral",       # bullish/bearish/neutral
            "macro_flow": "unclear",         # risk_on/risk_off/unclear
            "divergences": [],
            "signal_confirmation": None,
            "confidence": 0.0,
            "should_avoid_long": False,
            "should_avoid_short": False,
            "details": {}
        }

        symbol = symbol.upper()
        related_pairs = self.get_related_pairs(symbol)

        if not related_pairs:
            result["details"]["message"] = f"No related markets found for {symbol}"
            return result

        bullish_signals = 0
        bearish_signals = 0
        total_weight = 0.0
        divergence_count = 0

        for pair in related_pairs:
            # Déterminer quel est le marché "autre"
            if pair.primary.upper() == symbol:
                other_symbol = pair.secondary.upper()
                is_primary = True
            else:
                other_symbol = pair.primary.upper()
                is_primary = False

            other_df = related_dfs.get(other_symbol)
            if other_df is None:
                continue

            # Analyser la paire
            if is_primary:
                corr_result = self.analyze_pair(pair, symbol_df, other_df)
            else:
                corr_result = self.analyze_pair(pair, other_df, symbol_df)

            result["correlations"].append({
                "pair": f"{pair.primary}/{pair.secondary}",
                "actual_correlation": corr_result.actual_correlation,
                "expected_correlation": pair.expected_correlation,
                "deviation": corr_result.deviation,
                "is_diverging": corr_result.is_diverging,
                "implication": corr_result.signal_implication,
                "confidence": corr_result.confidence
            })

            # Compter les signaux
            weight = pair.weight * corr_result.confidence
            total_weight += weight

            if corr_result.is_diverging:
                divergence_count += 1
                result["divergences"].append({
                    "pair": f"{pair.primary}/{pair.secondary}",
                    "description": pair.description,
                    "primary_trend": corr_result.primary_trend,
                    "secondary_trend": corr_result.secondary_trend
                })

            # Déterminer le biais pour notre symbole
            if is_primary:
                # Le symbole est le driver
                pass  # Pas d'implication directe
            else:
                # Le symbole est le follower
                if corr_result.signal_implication == "secondary_bullish":
                    bullish_signals += weight
                elif corr_result.signal_implication == "secondary_bearish":
                    bearish_signals += weight

        # Calculer le biais global
        if total_weight > 0:
            net_signal = (bullish_signals - bearish_signals) / total_weight

            if net_signal > 0.3:
                result["overall_bias"] = "bullish"
                result["should_avoid_short"] = True
            elif net_signal < -0.3:
                result["overall_bias"] = "bearish"
                result["should_avoid_long"] = True
            else:
                result["overall_bias"] = "neutral"

            result["confidence"] = min(abs(net_signal), 1.0)

        # Déterminer le flux macro
        if result["overall_bias"] == "bullish" and symbol in ["AUDUSD", "NZDUSD", "BTCUSD"]:
            result["macro_flow"] = "risk_on"
        elif result["overall_bias"] == "bearish" and symbol in ["USDJPY", "XAUUSD"]:
            result["macro_flow"] = "risk_off"
        elif divergence_count >= 2:
            result["macro_flow"] = "transitioning"

        # Signal de confirmation
        if divergence_count == 0 and result["confidence"] > 0.5:
            result["signal_confirmation"] = result["overall_bias"]

        return result

    def should_allow_trade(
        self,
        symbol: str,
        direction: str,
        analysis: Dict[str, Any]
    ) -> Tuple[bool, str, float]:
        """
        Vérifie si un trade est autorisé selon l'analyse inter-marchés.

        Args:
            symbol: Symbole à trader
            direction: "LONG" ou "SHORT"
            analysis: Résultat de analyze_symbol()

        Returns:
            Tuple[allowed, reason, confidence]
        """
        direction = direction.upper()

        # Si pas assez de données
        if analysis.get("confidence", 0) < 0.3:
            return True, "insufficient_correlation_data", 0.3

        # Vérifier les restrictions
        if direction == "LONG" and analysis.get("should_avoid_long", False):
            return False, f"macro_flow_bearish_{analysis.get('overall_bias')}", analysis["confidence"]

        if direction == "SHORT" and analysis.get("should_avoid_short", False):
            return False, f"macro_flow_bullish_{analysis.get('overall_bias')}", analysis["confidence"]

        # Vérifier les divergences (opportunité mais risque)
        divergences = analysis.get("divergences", [])
        if len(divergences) >= 2:
            return True, "divergence_opportunity_caution", 0.5

        # Trade aligné avec le macro flow
        if analysis.get("overall_bias") == "bullish" and direction == "LONG":
            return True, "macro_aligned_bullish", analysis["confidence"]

        if analysis.get("overall_bias") == "bearish" and direction == "SHORT":
            return True, "macro_aligned_bearish", analysis["confidence"]

        return True, "no_macro_conflict", 0.5


# Instance globale
_correlation_analyzer: Optional[InterMarketCorrelationAnalyzer] = None


def get_correlation_analyzer(
    config: Optional[InterMarketConfig] = None
) -> InterMarketCorrelationAnalyzer:
    """Récupère ou crée l'analyseur de corrélation"""
    global _correlation_analyzer

    if _correlation_analyzer is None:
        _correlation_analyzer = InterMarketCorrelationAnalyzer(config)

    return _correlation_analyzer


def analyze_inter_market_correlation(
    symbol: str,
    symbol_df: pd.DataFrame,
    related_dfs: Dict[str, pd.DataFrame],
    config: Optional[InterMarketConfig] = None
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour analyser la corrélation inter-marchés.

    Args:
        symbol: Symbole à analyser
        symbol_df: DataFrame OHLCV du symbole
        related_dfs: Dict des DataFrames des marchés liés
        config: Configuration optionnelle

    Returns:
        Dict avec bias, divergences, signal_confirmation, etc.
    """
    analyzer = get_correlation_analyzer(config)
    return analyzer.analyze_symbol(symbol, symbol_df, related_dfs)


def get_macro_bias(
    symbol: str,
    direction: str,
    symbol_df: pd.DataFrame,
    related_dfs: Dict[str, pd.DataFrame]
) -> Tuple[bool, str]:
    """
    Vérifie rapidement si un trade est aligné avec le flux macro.

    Returns:
        Tuple[is_aligned, reason]
    """
    analyzer = get_correlation_analyzer()
    analysis = analyzer.analyze_symbol(symbol, symbol_df, related_dfs)
    allowed, reason, _ = analyzer.should_allow_trade(symbol, direction, analysis)
    return allowed, reason
