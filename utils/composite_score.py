# utils/composite_score.py
"""
SCORE COMPOSITE - Unification de tous les signaux en un score final
(PHASE 3 - Amélioration 2025-12-17)

Fonctionnalités:
1. Combine score agents, volume profile, inter-market, sentiment
2. Pondération configurable de chaque composant
3. Optimisation automatique des SL/TP via Volume Profile
4. Calcul de confiance globale
5. Logging détaillé pour debug

Formule:
SCORE_FINAL = w1 * score_agents
            + w2 * volume_profile_score
            + w3 * inter_market_alignment
            + w4 * sentiment_score

Objectif: Score final unifié pour décision de trade optimale.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import threading

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# Imports optionnels des modules d'analyse
try:
    from agents.volume_profile import VolumeProfileAgent, create_volume_profile_agent
    VOLUME_PROFILE_AVAILABLE = True
except ImportError:
    VOLUME_PROFILE_AVAILABLE = False
    VolumeProfileAgent = None

try:
    from utils.inter_market_correlation import (
        analyze_inter_market_correlation,
        get_correlation_analyzer,
        InterMarketCorrelationAnalyzer
    )
    INTER_MARKET_AVAILABLE = True
except ImportError:
    INTER_MARKET_AVAILABLE = False

try:
    from utils.advanced_sentiment_v2 import get_sentiment_analyzer, analyze_news_sentiment
    SENTIMENT_V2_AVAILABLE = True
except ImportError:
    SENTIMENT_V2_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class CompositeScoreConfig:
    """Configuration du score composite"""
    # Poids des composants (doivent sommer à 1.0)
    weight_agents: float = 0.50      # Score des agents IA
    weight_volume_profile: float = 0.20   # Volume Profile (VWAP, POC)
    weight_inter_market: float = 0.15     # Corrélation inter-marchés
    weight_sentiment: float = 0.15        # Sentiment news

    # Seuils
    min_composite_score: float = 5.0      # Score minimum pour trader
    min_confidence: float = 0.4           # Confiance minimum
    volume_profile_sl_buffer: float = 0.002  # Buffer pour SL (0.2%)
    volume_profile_tp_multiplier: float = 1.5  # Multiplicateur pour TP

    # Activation des composants
    enable_volume_profile: bool = True
    enable_inter_market: bool = True
    enable_sentiment: bool = True

    # Volume Profile
    vp_timeframe: str = "H1"
    vp_lookback_bars: int = 100

    def validate(self):
        """Valide que les poids somment à 1.0"""
        total = (self.weight_agents + self.weight_volume_profile +
                self.weight_inter_market + self.weight_sentiment)
        if abs(total - 1.0) > 0.01:
            logger.warning(f"[COMPOSITE] Poids ne somment pas à 1.0: {total:.2f}")


# =============================================================================
# COMPOSITE SCORE CALCULATOR
# =============================================================================

@dataclass
class CompositeResult:
    """Résultat du calcul de score composite"""
    # Score final
    composite_score: float
    composite_confidence: float
    signal: Optional[str]  # LONG, SHORT, ou None

    # Composants
    agents_score: float
    agents_confluence: int
    volume_profile_score: float
    inter_market_score: float
    sentiment_score: float

    # Détails Volume Profile
    vp_vwap: Optional[float] = None
    vp_poc: Optional[float] = None
    vp_vah: Optional[float] = None
    vp_val: Optional[float] = None
    vp_suggested_sl: Optional[float] = None
    vp_suggested_tp: Optional[float] = None

    # Détails Inter-Market
    im_bias: str = "neutral"
    im_should_avoid_long: bool = False
    im_should_avoid_short: bool = False

    # Détails Sentiment
    sent_level: str = "neutral"
    sent_signal: Optional[str] = None

    # Méta
    timestamp: str = ""
    symbol: str = ""
    breakdown: Dict[str, Any] = field(default_factory=dict)


class CompositeScoreCalculator:
    """
    Calculateur de score composite unifiant tous les signaux.
    """

    def __init__(
        self,
        config: Optional[CompositeScoreConfig] = None,
        mt5=None
    ):
        self.config = config or CompositeScoreConfig()
        self.config.validate()
        self.mt5 = mt5

        # Cache des analyseurs
        self._vp_agents: Dict[str, VolumeProfileAgent] = {}
        self._lock = threading.Lock()

        logger.info(f"[COMPOSITE] Initialisé avec poids: "
                   f"agents={self.config.weight_agents:.0%}, "
                   f"VP={self.config.weight_volume_profile:.0%}, "
                   f"IM={self.config.weight_inter_market:.0%}, "
                   f"sent={self.config.weight_sentiment:.0%}")

    def _get_vp_agent(self, symbol: str) -> Optional[VolumeProfileAgent]:
        """Récupère ou crée un agent Volume Profile pour un symbole"""
        if not VOLUME_PROFILE_AVAILABLE or not self.config.enable_volume_profile:
            return None

        with self._lock:
            if symbol not in self._vp_agents:
                try:
                    self._vp_agents[symbol] = create_volume_profile_agent(
                        symbol=symbol,
                        mt5=self.mt5,
                        params={
                            "timeframe": self.config.vp_timeframe,
                            "lookback_bars": self.config.vp_lookback_bars
                        }
                    )
                except Exception as e:
                    logger.debug(f"[COMPOSITE] Erreur création VP agent {symbol}: {e}")
                    return None

            return self._vp_agents.get(symbol)

    def calculate_volume_profile_score(
        self,
        symbol: str,
        current_price: float,
        direction: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calcule le score Volume Profile.

        Returns:
            Tuple[score (-1 à 1), details]
        """
        details = {
            "vwap": None,
            "poc": None,
            "vah": None,
            "val": None,
            "suggested_sl": None,
            "suggested_tp": None,
            "price_position": "unknown"
        }

        if not VOLUME_PROFILE_AVAILABLE or not self.config.enable_volume_profile:
            return 0.0, details

        try:
            vp_agent = self._get_vp_agent(symbol)
            if vp_agent is None:
                return 0.0, details

            result = vp_agent.get_signal(current_price)

            details["vwap"] = result.get("vwap")
            details["poc"] = result.get("poc")
            details["vah"] = result.get("vah")
            details["val"] = result.get("val")
            details["suggested_sl"] = result.get("suggested_sl")
            details["suggested_tp"] = result.get("suggested_tp")

            # Calculer le score basé sur la position du prix
            vwap = result.get("vwap", 0)
            poc = result.get("poc", 0)
            vah = result.get("vah", 0)
            val = result.get("val", 0)

            if not vwap or not poc:
                return 0.0, details

            score = 0.0
            confidence = result.get("confidence", 0.5)

            # Position relative au VWAP et POC
            price_vs_vwap = result.get("price_vs_vwap", "neutral")
            price_vs_poc = result.get("price_vs_poc", "neutral")
            in_value_area = result.get("in_value_area", False)

            if direction == "LONG":
                # LONG favorable si prix sous VWAP et POC (potentiel de hausse)
                if price_vs_vwap == "below" and price_vs_poc == "below":
                    score = 0.8 * confidence
                    details["price_position"] = "below_vwap_poc_bullish"
                elif price_vs_vwap == "below":
                    score = 0.5 * confidence
                    details["price_position"] = "below_vwap"
                elif in_value_area:
                    score = 0.3 * confidence
                    details["price_position"] = "in_value_area"
                else:
                    score = -0.3 * confidence  # Prix déjà haut
                    details["price_position"] = "above_vwap_poc"

            elif direction == "SHORT":
                # SHORT favorable si prix au-dessus VWAP et POC
                if price_vs_vwap == "above" and price_vs_poc == "above":
                    score = 0.8 * confidence
                    details["price_position"] = "above_vwap_poc_bearish"
                elif price_vs_vwap == "above":
                    score = 0.5 * confidence
                    details["price_position"] = "above_vwap"
                elif in_value_area:
                    score = 0.3 * confidence
                    details["price_position"] = "in_value_area"
                else:
                    score = -0.3 * confidence  # Prix déjà bas
                    details["price_position"] = "below_vwap_poc"

            return score, details

        except Exception as e:
            logger.debug(f"[COMPOSITE] Erreur calcul VP: {e}")
            return 0.0, details

    def calculate_inter_market_score(
        self,
        symbol: str,
        direction: str,
        symbol_df=None,
        related_dfs: Dict = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calcule le score Inter-Market.

        Returns:
            Tuple[score (-1 à 1), details]
        """
        details = {
            "bias": "neutral",
            "should_avoid_long": False,
            "should_avoid_short": False,
            "macro_flow": "unclear",
            "correlations": []
        }

        if not INTER_MARKET_AVAILABLE or not self.config.enable_inter_market:
            return 0.0, details

        try:
            # Si pas de DataFrames fournis, on ne peut pas calculer
            if symbol_df is None or not related_dfs:
                return 0.0, details

            analysis = analyze_inter_market_correlation(
                symbol=symbol,
                symbol_df=symbol_df,
                related_dfs=related_dfs
            )

            details["bias"] = analysis.get("overall_bias", "neutral")
            details["should_avoid_long"] = analysis.get("should_avoid_long", False)
            details["should_avoid_short"] = analysis.get("should_avoid_short", False)
            details["macro_flow"] = analysis.get("macro_flow", "unclear")
            details["correlations"] = analysis.get("correlations", [])[:3]

            # Calculer le score
            score = 0.0
            confidence = analysis.get("confidence", 0.5)

            bias = analysis.get("overall_bias", "neutral")

            if direction == "LONG":
                if details["should_avoid_long"]:
                    score = -0.8  # Forte pénalité
                elif bias == "bullish":
                    score = 0.7 * confidence
                elif bias == "bearish":
                    score = -0.5 * confidence
                else:
                    score = 0.0

            elif direction == "SHORT":
                if details["should_avoid_short"]:
                    score = -0.8
                elif bias == "bearish":
                    score = 0.7 * confidence
                elif bias == "bullish":
                    score = -0.5 * confidence
                else:
                    score = 0.0

            return score, details

        except Exception as e:
            logger.debug(f"[COMPOSITE] Erreur calcul IM: {e}")
            return 0.0, details

    def calculate_sentiment_score(
        self,
        symbol: str,
        direction: str,
        news_items: List[Dict] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calcule le score Sentiment.

        Returns:
            Tuple[score (-1 à 1), details]
        """
        details = {
            "level": "neutral",
            "signal": None,
            "confidence": 0.0,
            "bullish_count": 0,
            "bearish_count": 0
        }

        if not SENTIMENT_V2_AVAILABLE or not self.config.enable_sentiment:
            return 0.0, details

        if not news_items:
            return 0.0, details

        try:
            result = analyze_news_sentiment(news_items, symbol)

            details["level"] = result.get("level", "neutral")
            details["signal"] = result.get("signal")
            details["confidence"] = result.get("confidence", 0.0)
            details["bullish_count"] = result.get("bullish_count", 0)
            details["bearish_count"] = result.get("bearish_count", 0)

            # Calculer le score
            sent_score = result.get("score", 0.0)
            confidence = result.get("confidence", 0.5)

            if direction == "LONG":
                # Sentiment positif = bon pour LONG
                score = sent_score * confidence
            elif direction == "SHORT":
                # Sentiment négatif = bon pour SHORT
                score = -sent_score * confidence
            else:
                score = 0.0

            return score, details

        except Exception as e:
            logger.debug(f"[COMPOSITE] Erreur calcul sentiment: {e}")
            return 0.0, details

    def calculate(
        self,
        symbol: str,
        direction: str,
        agents_score: float,
        agents_confluence: int,
        current_price: float,
        original_sl: float,
        original_tp: float,
        symbol_df=None,
        related_dfs: Dict = None,
        news_items: List[Dict] = None
    ) -> CompositeResult:
        """
        Calcule le score composite final.

        Args:
            symbol: Symbole tradé
            direction: LONG ou SHORT
            agents_score: Score agrégé des agents IA
            agents_confluence: Nombre d'agents en accord
            current_price: Prix actuel
            original_sl: SL original calculé
            original_tp: TP original calculé
            symbol_df: DataFrame OHLCV du symbole (optionnel)
            related_dfs: DataFrames des marchés corrélés (optionnel)
            news_items: Liste de news pour sentiment (optionnel)

        Returns:
            CompositeResult avec score final et détails
        """
        result = CompositeResult(
            composite_score=0.0,
            composite_confidence=0.0,
            signal=direction,
            agents_score=agents_score,
            agents_confluence=agents_confluence,
            volume_profile_score=0.0,
            inter_market_score=0.0,
            sentiment_score=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol
        )

        breakdown = {}

        # 1. Normaliser le score agents (typiquement 0-20 -> 0-1)
        agents_normalized = min(1.0, agents_score / 20.0)
        breakdown["agents"] = {
            "raw": agents_score,
            "normalized": agents_normalized,
            "confluence": agents_confluence
        }

        # 2. Volume Profile Score
        vp_score, vp_details = self.calculate_volume_profile_score(
            symbol, current_price, direction
        )
        result.volume_profile_score = vp_score
        result.vp_vwap = vp_details.get("vwap")
        result.vp_poc = vp_details.get("poc")
        result.vp_vah = vp_details.get("vah")
        result.vp_val = vp_details.get("val")
        result.vp_suggested_sl = vp_details.get("suggested_sl")
        result.vp_suggested_tp = vp_details.get("suggested_tp")
        breakdown["volume_profile"] = vp_details

        # 3. Inter-Market Score
        im_score, im_details = self.calculate_inter_market_score(
            symbol, direction, symbol_df, related_dfs
        )
        result.inter_market_score = im_score
        result.im_bias = im_details.get("bias", "neutral")
        result.im_should_avoid_long = im_details.get("should_avoid_long", False)
        result.im_should_avoid_short = im_details.get("should_avoid_short", False)
        breakdown["inter_market"] = im_details

        # 4. Sentiment Score
        sent_score, sent_details = self.calculate_sentiment_score(
            symbol, direction, news_items
        )
        result.sentiment_score = sent_score
        result.sent_level = sent_details.get("level", "neutral")
        result.sent_signal = sent_details.get("signal")
        breakdown["sentiment"] = sent_details

        # 5. Calculer le score composite pondéré
        # FIX 2026-02-20: Redistribution poids si composants indisponibles (étape 5.4)
        _w_agents = self.config.weight_agents
        _w_vp = self.config.weight_volume_profile if vp_score != 0.0 else 0.0
        _w_im = self.config.weight_inter_market if im_score != 0.0 else 0.0
        _w_sent = self.config.weight_sentiment if sent_score != 0.0 else 0.0
        _w_total = _w_agents + _w_vp + _w_im + _w_sent
        if _w_total > 0:
            _w_agents /= _w_total
            _w_vp /= _w_total
            _w_im /= _w_total
            _w_sent /= _w_total

        # Convertir en échelle 0-20 pour compatibilité avec le système existant
        weighted_score = (
            _w_agents * agents_normalized +
            _w_vp * (vp_score + 1) / 2 +  # -1,1 -> 0,1
            _w_im * (im_score + 1) / 2 +
            _w_sent * (sent_score + 1) / 2
        )

        # Reconvertir en échelle 0-20
        result.composite_score = weighted_score * 20.0
        breakdown["weight_redistribution"] = {
            "agents": round(_w_agents, 3), "vp": round(_w_vp, 3),
            "im": round(_w_im, 3), "sent": round(_w_sent, 3)
        }

        # 6. Calculer la confiance globale
        # Moyenne pondérée des confiances de chaque composant
        confidences = [
            (self.config.weight_agents, min(1.0, agents_confluence / 6)),
            (self.config.weight_volume_profile, abs(vp_score)),
            (self.config.weight_inter_market, abs(im_score)),
            (self.config.weight_sentiment, sent_details.get("confidence", 0.0))
        ]
        total_weight = sum(w for w, _ in confidences)
        result.composite_confidence = sum(w * c for w, c in confidences) / total_weight if total_weight > 0 else 0.0

        # 7. Vérifier les blocages
        if direction == "LONG" and result.im_should_avoid_long:
            result.signal = None
            breakdown["blocked"] = "inter_market_avoid_long"
        elif direction == "SHORT" and result.im_should_avoid_short:
            result.signal = None
            breakdown["blocked"] = "inter_market_avoid_short"

        result.breakdown = breakdown

        logger.info(f"[COMPOSITE] {symbol} {direction}: score={result.composite_score:.1f} "
                   f"(agents={agents_score:.1f}, VP={vp_score:+.2f}, IM={im_score:+.2f}, "
                   f"sent={sent_score:+.2f}) conf={result.composite_confidence:.2f}")

        return result

    def optimize_sl_tp(
        self,
        result: CompositeResult,
        original_sl: float,
        original_tp: float,
        current_price: float,
        direction: str
    ) -> Tuple[float, float]:
        """
        Optimise le SL et TP en utilisant les niveaux du Volume Profile.

        Returns:
            Tuple[optimized_sl, optimized_tp]
        """
        sl = original_sl
        tp = original_tp

        # Utiliser les suggestions du Volume Profile si disponibles
        if result.vp_suggested_sl and self.config.enable_volume_profile:
            vp_sl = result.vp_suggested_sl

            if direction == "LONG":
                # Pour LONG, SL doit être sous le prix
                if vp_sl < current_price:
                    # Prendre le plus conservateur (le plus proche du prix)
                    sl = max(vp_sl, original_sl) if original_sl < current_price else vp_sl
            else:
                # Pour SHORT, SL doit être au-dessus du prix
                if vp_sl > current_price:
                    sl = min(vp_sl, original_sl) if original_sl > current_price else vp_sl

        if result.vp_suggested_tp and self.config.enable_volume_profile:
            vp_tp = result.vp_suggested_tp

            if direction == "LONG":
                # Pour LONG, TP doit être au-dessus du prix
                if vp_tp > current_price:
                    # Prendre le plus ambitieux si Volume Profile suggère plus haut
                    tp = max(vp_tp, original_tp)
            else:
                # Pour SHORT, TP doit être sous le prix
                if vp_tp < current_price:
                    tp = min(vp_tp, original_tp)

        # Utiliser POC comme référence si pas de suggestion directe
        if result.vp_poc and not result.vp_suggested_tp:
            poc = result.vp_poc
            if direction == "LONG" and poc > current_price:
                tp = max(tp, poc)
            elif direction == "SHORT" and poc < current_price:
                tp = min(tp, poc)

        logger.debug(f"[COMPOSITE] SL/TP optimisé: original=({original_sl:.5f}, {original_tp:.5f}) "
                    f"-> optimisé=({sl:.5f}, {tp:.5f})")

        return sl, tp


# =============================================================================
# INSTANCE GLOBALE ET FONCTIONS UTILITAIRES
# =============================================================================

_composite_calculator: Optional[CompositeScoreCalculator] = None


def get_composite_calculator(
    config: Optional[CompositeScoreConfig] = None,
    mt5=None
) -> CompositeScoreCalculator:
    """Récupère ou crée l'instance globale du calculateur composite"""
    global _composite_calculator

    if _composite_calculator is None:
        _composite_calculator = CompositeScoreCalculator(config, mt5)

    return _composite_calculator


def calculate_composite_score(
    symbol: str,
    direction: str,
    agents_score: float,
    agents_confluence: int,
    current_price: float,
    original_sl: float = 0.0,
    original_tp: float = 0.0,
    **kwargs
) -> CompositeResult:
    """Fonction utilitaire pour calculer le score composite"""
    calculator = get_composite_calculator()
    return calculator.calculate(
        symbol=symbol,
        direction=direction,
        agents_score=agents_score,
        agents_confluence=agents_confluence,
        current_price=current_price,
        original_sl=original_sl,
        original_tp=original_tp,
        **kwargs
    )
