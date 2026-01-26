# utils/mtf_confluence.py
"""
OUTIL 3: Multi-Timeframe Confluence Analyzer (OPTIMISATION 2025-12-13)

Analyse renforcée de la confluence multi-timeframes:
1. Alignement des tendances sur H4/D1/W1
2. Score de confluence pondéré par timeframe
3. Détection des divergences inter-timeframes
4. Validation des entrées par les timeframes supérieurs

Objectif: Éviter les trades contre-tendance sur les TF supérieurs.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum

import pandas as pd
import numpy as np

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class TrendDirection(Enum):
    """Direction de la tendance"""
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


@dataclass
class MTFConfig:
    """Configuration de l'analyse MTF"""
    # Timeframes à analyser (du plus petit au plus grand)
    timeframes: List[str] = field(default_factory=lambda: ["M15", "H1", "H4", "D1"])

    # Poids par timeframe (plus le TF est grand, plus le poids est important)
    tf_weights: Dict[str, float] = field(default_factory=lambda: {
        "M1": 0.5, "M5": 0.6, "M15": 0.7, "M30": 0.8,
        "H1": 1.0, "H4": 1.3, "D1": 1.5, "W1": 1.8
    })

    # Seuils
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70
    rsi_oversold: float = 30

    # Confluence requise
    min_alignment_ratio: float = 0.6      # 60% des TF doivent être alignés
    require_higher_tf_confirm: bool = True # Exiger confirmation du TF supérieur

    # Bonus/Malus
    full_alignment_bonus: float = 0.3      # Bonus si 100% aligné
    divergence_penalty: float = 0.4        # Pénalité si divergence


class TimeframeAnalysis:
    """Analyse d'un timeframe unique"""

    def __init__(self, timeframe: str, df: pd.DataFrame, config: MTFConfig):
        self.timeframe = timeframe
        self.df = df
        self.config = config

        self.trend: TrendDirection = TrendDirection.NEUTRAL
        self.trend_strength: float = 0.0
        self.rsi: float = 50.0
        self.ema_fast: float = 0.0
        self.ema_slow: float = 0.0
        self.price_vs_ema: str = "neutral"

        self._analyze()

    def _analyze(self):
        """Analyse le timeframe"""
        if self.df is None or len(self.df) < self.config.ema_slow:
            return

        try:
            close = self.df['close']

            # EMAs
            self.ema_fast = close.ewm(span=self.config.ema_fast, adjust=False).mean().iloc[-1]
            self.ema_slow = close.ewm(span=self.config.ema_slow, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]

            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.config.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.config.rsi_period).mean()
            rs = gain / loss.replace(0, 1e-10)
            rsi = 100 - (100 / (1 + rs))
            self.rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

            # Position du prix vs EMAs
            if current_price > self.ema_fast > self.ema_slow:
                self.price_vs_ema = "above_both"
            elif current_price < self.ema_fast < self.ema_slow:
                self.price_vs_ema = "below_both"
            elif current_price > self.ema_slow:
                self.price_vs_ema = "above_slow"
            elif current_price < self.ema_slow:
                self.price_vs_ema = "below_slow"
            else:
                self.price_vs_ema = "neutral"

            # Déterminer la tendance
            ema_spread = (self.ema_fast - self.ema_slow) / self.ema_slow
            price_ema_spread = (current_price - self.ema_slow) / self.ema_slow

            if ema_spread > 0.02 and price_ema_spread > 0.02:
                self.trend = TrendDirection.STRONG_UP
                self.trend_strength = min(abs(ema_spread) * 20 + abs(price_ema_spread) * 10, 1.0)
            elif ema_spread > 0.005 or (self.ema_fast > self.ema_slow and current_price > self.ema_fast):
                self.trend = TrendDirection.UP
                self.trend_strength = min(abs(ema_spread) * 15 + 0.3, 0.8)
            elif ema_spread < -0.02 and price_ema_spread < -0.02:
                self.trend = TrendDirection.STRONG_DOWN
                self.trend_strength = min(abs(ema_spread) * 20 + abs(price_ema_spread) * 10, 1.0)
            elif ema_spread < -0.005 or (self.ema_fast < self.ema_slow and current_price < self.ema_fast):
                self.trend = TrendDirection.DOWN
                self.trend_strength = min(abs(ema_spread) * 15 + 0.3, 0.8)
            else:
                self.trend = TrendDirection.NEUTRAL
                self.trend_strength = 0.2

        except Exception as e:
            logger.debug(f"[MTF] Erreur analyse {self.timeframe}: {e}")

    def get_signal(self) -> str:
        """Retourne le signal du timeframe"""
        if self.trend in (TrendDirection.STRONG_UP, TrendDirection.UP):
            return "LONG"
        elif self.trend in (TrendDirection.STRONG_DOWN, TrendDirection.DOWN):
            return "SHORT"
        return "WAIT"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire"""
        return {
            "timeframe": self.timeframe,
            "trend": self.trend.value,
            "trend_strength": self.trend_strength,
            "signal": self.get_signal(),
            "rsi": self.rsi,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "price_vs_ema": self.price_vs_ema
        }


class MTFConfluenceAnalyzer:
    """
    Analyseur de confluence multi-timeframes.

    Évalue l'alignement des signaux sur plusieurs timeframes
    pour confirmer ou invalider un trade.
    """

    def __init__(self, symbol: str, config: Optional[MTFConfig] = None):
        self.symbol = symbol.upper()
        self.config = config or MTFConfig()
        self._analyses: Dict[str, TimeframeAnalysis] = {}

    def analyze_timeframe(self, timeframe: str, df: pd.DataFrame) -> TimeframeAnalysis:
        """Analyse un timeframe et le stocke"""
        analysis = TimeframeAnalysis(timeframe, df, self.config)
        self._analyses[timeframe] = analysis
        return analysis

    def get_confluence_score(self, target_direction: str) -> Dict[str, Any]:
        """
        Calcule le score de confluence pour une direction donnée.

        Args:
            target_direction: "LONG" ou "SHORT"

        Returns:
            Dict avec score, aligned_tfs, divergent_tfs, etc.
        """
        result = {
            "direction": target_direction,
            "confluence_score": 0.0,
            "aligned_count": 0,
            "total_count": 0,
            "alignment_ratio": 0.0,
            "aligned_tfs": [],
            "divergent_tfs": [],
            "neutral_tfs": [],
            "weighted_score": 0.0,
            "higher_tf_confirms": False,
            "divergence_detected": False,
            "recommendation": "WAIT",
            "details": {}
        }

        if not self._analyses:
            return result

        target_direction = target_direction.upper()
        opposite = "SHORT" if target_direction == "LONG" else "LONG"

        total_weight = 0.0
        aligned_weight = 0.0
        divergent_weight = 0.0

        for tf, analysis in self._analyses.items():
            tf_weight = self.config.tf_weights.get(tf, 1.0)
            total_weight += tf_weight
            signal = analysis.get_signal()

            result["details"][tf] = analysis.to_dict()

            if signal == target_direction:
                result["aligned_tfs"].append(tf)
                aligned_weight += tf_weight * analysis.trend_strength
            elif signal == opposite:
                result["divergent_tfs"].append(tf)
                divergent_weight += tf_weight * analysis.trend_strength
            else:
                result["neutral_tfs"].append(tf)

        result["aligned_count"] = len(result["aligned_tfs"])
        result["total_count"] = len(self._analyses)
        result["alignment_ratio"] = result["aligned_count"] / max(result["total_count"], 1)

        # Score de confluence pondéré
        if total_weight > 0:
            result["weighted_score"] = (aligned_weight - divergent_weight * 0.5) / total_weight

        # Vérifier confirmation du TF supérieur
        if self.config.require_higher_tf_confirm:
            sorted_tfs = sorted(
                self._analyses.keys(),
                key=lambda x: self.config.tf_weights.get(x, 1.0),
                reverse=True
            )
            if sorted_tfs:
                highest_tf = sorted_tfs[0]
                highest_signal = self._analyses[highest_tf].get_signal()
                result["higher_tf_confirms"] = (highest_signal == target_direction)
                result["highest_tf"] = highest_tf
                result["highest_tf_signal"] = highest_signal

        # Détecter divergence (TF supérieur contre, TF inférieur pour)
        if result["divergent_tfs"]:
            for div_tf in result["divergent_tfs"]:
                div_weight = self.config.tf_weights.get(div_tf, 1.0)
                for align_tf in result["aligned_tfs"]:
                    align_weight = self.config.tf_weights.get(align_tf, 1.0)
                    if div_weight > align_weight:
                        result["divergence_detected"] = True
                        break

        # Calculer le score final
        base_score = result["weighted_score"]

        # Bonus si 100% aligné
        if result["alignment_ratio"] >= 1.0:
            base_score += self.config.full_alignment_bonus

        # Pénalité si divergence avec TF supérieur
        if result["divergence_detected"]:
            base_score -= self.config.divergence_penalty

        # Pénalité si TF supérieur ne confirme pas
        if self.config.require_higher_tf_confirm and not result["higher_tf_confirms"]:
            base_score -= 0.2

        result["confluence_score"] = max(min(base_score, 1.0), -1.0)

        # Recommandation
        if result["confluence_score"] >= 0.5 and result["alignment_ratio"] >= self.config.min_alignment_ratio:
            if result["higher_tf_confirms"] or not self.config.require_higher_tf_confirm:
                result["recommendation"] = target_direction
            else:
                result["recommendation"] = "WAIT_HTF"
        elif result["confluence_score"] <= -0.3:
            result["recommendation"] = opposite
        else:
            result["recommendation"] = "WAIT"

        return result

    def should_allow_trade(self, direction: str) -> Tuple[bool, str, float]:
        """
        Vérifie si un trade est autorisé selon la confluence MTF.

        Args:
            direction: "LONG" ou "SHORT"

        Returns:
            Tuple[allowed, reason, score]
        """
        confluence = self.get_confluence_score(direction)

        score = confluence["confluence_score"]
        ratio = confluence["alignment_ratio"]

        # Refus si score trop bas
        if score < 0.2:
            return False, f"low_mtf_score({score:.2f})", score

        # Refus si trop peu de TF alignés
        if ratio < self.config.min_alignment_ratio:
            return False, f"low_alignment({ratio:.0%})", score

        # Refus si divergence avec TF supérieur
        if confluence["divergence_detected"]:
            return False, "htf_divergence", score

        # Refus si TF supérieur ne confirme pas (si requis)
        if self.config.require_higher_tf_confirm and not confluence["higher_tf_confirms"]:
            htf = confluence.get("highest_tf", "?")
            htf_sig = confluence.get("highest_tf_signal", "?")
            return False, f"htf_{htf}_is_{htf_sig}", score

        return True, "mtf_confirmed", score


# Cache global
_mtf_analyzers: Dict[str, MTFConfluenceAnalyzer] = {}


def get_mtf_analyzer(symbol: str, config: Optional[MTFConfig] = None) -> MTFConfluenceAnalyzer:
    """Récupère ou crée un analyseur MTF pour un symbole"""
    global _mtf_analyzers

    symbol = symbol.upper()
    if symbol not in _mtf_analyzers:
        _mtf_analyzers[symbol] = MTFConfluenceAnalyzer(symbol, config)

    return _mtf_analyzers[symbol]


def analyze_mtf_confluence(
    symbol: str,
    direction: str,
    tf_data: Dict[str, pd.DataFrame],
    config: Optional[MTFConfig] = None
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour analyser la confluence MTF.

    Args:
        symbol: Symbole à analyser
        direction: Direction du trade ("LONG" ou "SHORT")
        tf_data: Dict[timeframe] -> DataFrame OHLCV
        config: Configuration optionnelle

    Returns:
        Dict avec confluence_score, recommendation, details
    """
    analyzer = get_mtf_analyzer(symbol, config)

    # Analyser chaque timeframe
    for tf, df in tf_data.items():
        analyzer.analyze_timeframe(tf, df)

    return analyzer.get_confluence_score(direction)
