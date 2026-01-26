# utils/advanced_sentiment_v2.py
"""
SENTIMENT AVANCÉ V2 - Analyse de sentiment financier améliorée
(PHASE 2 - Amélioration 2025-12-17)

Fonctionnalités:
1. FinBERT pour analyse sentiment financier (remplace TextBlob)
2. Pondération des sources par fiabilité (Reuters > CoinDesk > Génériques)
3. Détection d'entités (symbole spécifique vs marché général)
4. Sentiment agrégé multi-sources avec confiance
5. Cache intelligent pour éviter recalculs

Objectif: Réduire les faux positifs/négatifs et améliorer la précision du sentiment.
"""

from __future__ import annotations
import os
import json
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import threading
import re

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# Essayer d'importer les transformers pour FinBERT
FINBERT_AVAILABLE = False
_finbert_model = None
_finbert_tokenizer = None

try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
    import torch
    FINBERT_AVAILABLE = True
except ImportError:
    logger.warning("[SENTIMENT_V2] transformers non disponible - fallback TextBlob")

# Fallback TextBlob
try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

class SentimentLevel(Enum):
    """Niveau de sentiment"""
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


@dataclass
class SourceWeight:
    """Poids d'une source de news"""
    name: str
    weight: float       # 0.0 à 1.0
    reliability: float  # Fiabilité historique
    bias: float         # Biais connu (-1 bearish, +1 bullish, 0 neutre)


@dataclass
class SentimentConfig:
    """Configuration du sentiment avancé"""
    # Modèle
    use_finbert: bool = True
    finbert_model: str = "ProsusAI/finbert"
    fallback_to_textblob: bool = True

    # Seuils
    bullish_threshold: float = 0.3
    bearish_threshold: float = -0.3
    very_bullish_threshold: float = 0.6
    very_bearish_threshold: float = -0.6
    min_confidence: float = 0.5

    # Cache
    cache_ttl_seconds: int = 300
    cache_dir: str = "data/sentiment_cache"

    # Sources et leurs poids
    source_weights: Dict[str, float] = field(default_factory=lambda: {
        # Tier 1 - Sources premium
        "reuters": 1.0,
        "bloomberg": 1.0,
        "wsj": 0.95,
        "ft": 0.95,

        # Tier 2 - Sources crypto spécialisées
        "coindesk": 0.85,
        "cointelegraph": 0.80,
        "theblock": 0.85,
        "decrypt": 0.75,

        # Tier 3 - Sources générales
        "yahoo": 0.60,
        "marketwatch": 0.65,
        "cnbc": 0.60,
        "investing": 0.55,

        # Tier 4 - Agrégateurs/Blogs
        "cryptoslate": 0.50,
        "bitcoinmagazine": 0.55,
        "coinjournal": 0.45,
        "google": 0.40,
        "other": 0.30,
    })

    # Mots-clés de renforcement
    strong_bullish_keywords: List[str] = field(default_factory=lambda: [
        "approved", "approval", "etf approved", "spot etf", "institutional adoption",
        "major partnership", "breakthrough", "all-time high", "record high",
        "massive buying", "whale accumulation", "fed pivot", "rate cut"
    ])

    strong_bearish_keywords: List[str] = field(default_factory=lambda: [
        "hack", "hacked", "exploit", "stolen", "scam", "fraud", "ponzi",
        "sec charges", "lawsuit", "banned", "crash", "collapse", "liquidation",
        "massive selling", "whale dump", "bank failure", "default"
    ])

    # Entités pour filtrage par symbole
    symbol_entities: Dict[str, List[str]] = field(default_factory=lambda: {
        "BTCUSD": ["bitcoin", "btc", "satoshi"],
        "ETHUSD": ["ethereum", "eth", "vitalik", "ether"],
        "SOLUSD": ["solana", "sol"],
        "ADAUSD": ["cardano", "ada"],
        "XAUUSD": ["gold", "xau", "precious metal", "bullion"],
        "EURUSD": ["euro", "eur", "ecb", "lagarde", "eurozone"],
        "USDJPY": ["yen", "jpy", "boj", "japan"],
        "GBPUSD": ["pound", "gbp", "boe", "sterling", "uk economy"],
    })


# =============================================================================
# FINBERT ANALYZER
# =============================================================================

class FinBERTAnalyzer:
    """Analyseur de sentiment basé sur FinBERT"""

    def __init__(self, config: SentimentConfig):
        self.config = config
        self._model = None
        self._tokenizer = None
        self._pipeline = None
        self._loaded = False
        self._lock = threading.Lock()

    def _load_model(self) -> bool:
        """Charge le modèle FinBERT (lazy loading)"""
        if self._loaded:
            return True

        if not FINBERT_AVAILABLE:
            return False

        with self._lock:
            if self._loaded:
                return True

            try:
                logger.info(f"[SENTIMENT_V2] Chargement FinBERT: {self.config.finbert_model}")

                self._tokenizer = AutoTokenizer.from_pretrained(self.config.finbert_model)
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.config.finbert_model
                )

                # Utiliser GPU si disponible
                device = 0 if torch.cuda.is_available() else -1

                self._pipeline = pipeline(
                    "sentiment-analysis",
                    model=self._model,
                    tokenizer=self._tokenizer,
                    device=device,
                    truncation=True,
                    max_length=512
                )

                self._loaded = True
                logger.info("[SENTIMENT_V2] FinBERT chargé avec succès")
                return True

            except Exception as e:
                logger.error(f"[SENTIMENT_V2] Erreur chargement FinBERT: {e}")
                return False

    def analyze(self, text: str) -> Tuple[float, float]:
        """
        Analyse le sentiment d'un texte avec FinBERT.

        Returns:
            Tuple[score, confidence] où score est entre -1 et 1
        """
        if not text or len(text.strip()) < 10:
            return 0.0, 0.0

        if not self._load_model():
            return self._fallback_analyze(text)

        try:
            # FinBERT retourne: positive, negative, neutral
            results = self._pipeline(text[:512])  # Limiter à 512 tokens

            if not results:
                return 0.0, 0.0

            result = results[0]
            label = result.get("label", "neutral").lower()
            confidence = float(result.get("score", 0.5))

            # Convertir le label en score
            if label == "positive":
                score = confidence
            elif label == "negative":
                score = -confidence
            else:
                score = 0.0
                confidence *= 0.5  # Réduire confiance pour neutral

            return score, confidence

        except Exception as e:
            logger.debug(f"[SENTIMENT_V2] Erreur FinBERT: {e}")
            return self._fallback_analyze(text)

    def _fallback_analyze(self, text: str) -> Tuple[float, float]:
        """Fallback sur TextBlob si FinBERT non disponible"""
        if not TEXTBLOB_AVAILABLE:
            return 0.0, 0.0

        try:
            blob = TextBlob(text)
            polarity = blob.sentiment.polarity  # -1 à 1
            subjectivity = blob.sentiment.subjectivity  # 0 à 1

            # Confidence basée sur subjectivité inversée (plus objectif = plus fiable)
            confidence = max(0.3, 1.0 - subjectivity * 0.5)

            return polarity, confidence

        except Exception:
            return 0.0, 0.0

    def analyze_batch(self, texts: List[str]) -> List[Tuple[float, float]]:
        """Analyse un batch de textes"""
        return [self.analyze(text) for text in texts]


# =============================================================================
# ADVANCED SENTIMENT ANALYZER
# =============================================================================

class AdvancedSentimentAnalyzerV2:
    """
    Analyseur de sentiment avancé avec FinBERT, pondération des sources,
    et détection d'entités.
    """

    def __init__(self, config: Optional[SentimentConfig] = None):
        self.config = config or SentimentConfig()
        self.finbert = FinBERTAnalyzer(self.config)

        # Cache
        self._cache: Dict[str, Tuple[float, float, datetime]] = {}
        self._lock = threading.Lock()

        # Créer le répertoire de cache
        os.makedirs(self.config.cache_dir, exist_ok=True)

        logger.info("[SENTIMENT_V2] Analyseur avancé initialisé")

    def _get_cache_key(self, text: str) -> str:
        """Génère une clé de cache pour un texte"""
        return hashlib.md5(text.encode()).hexdigest()[:16]

    def _check_cache(self, text: str) -> Optional[Tuple[float, float]]:
        """Vérifie si le résultat est en cache"""
        key = self._get_cache_key(text)

        with self._lock:
            if key in self._cache:
                score, conf, timestamp = self._cache[key]
                age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                if age < self.config.cache_ttl_seconds:
                    return score, conf

        return None

    def _set_cache(self, text: str, score: float, confidence: float) -> None:
        """Met en cache un résultat"""
        key = self._get_cache_key(text)

        with self._lock:
            self._cache[key] = (score, confidence, datetime.now(timezone.utc))

            # Limiter la taille du cache
            if len(self._cache) > 1000:
                # Supprimer les entrées les plus anciennes
                sorted_items = sorted(
                    self._cache.items(),
                    key=lambda x: x[1][2]
                )
                for k, _ in sorted_items[:200]:
                    del self._cache[k]

    def get_source_weight(self, source: str) -> float:
        """Retourne le poids d'une source"""
        source_lower = source.lower() if source else "other"

        # Chercher le poids exact
        if source_lower in self.config.source_weights:
            return self.config.source_weights[source_lower]

        # Chercher une correspondance partielle
        for key, weight in self.config.source_weights.items():
            if key in source_lower or source_lower in key:
                return weight

        return self.config.source_weights.get("other", 0.3)

    def check_keyword_boost(self, text: str) -> float:
        """
        Vérifie les mots-clés de renforcement et retourne un boost.

        Returns:
            Boost entre -0.3 et +0.3
        """
        text_lower = text.lower()
        boost = 0.0

        # Mots-clés bullish
        for kw in self.config.strong_bullish_keywords:
            if kw in text_lower:
                boost += 0.15
                if boost >= 0.3:
                    return 0.3

        # Mots-clés bearish
        for kw in self.config.strong_bearish_keywords:
            if kw in text_lower:
                boost -= 0.15
                if boost <= -0.3:
                    return -0.3

        return boost

    def is_relevant_for_symbol(self, text: str, symbol: str) -> Tuple[bool, float]:
        """
        Vérifie si un texte est pertinent pour un symbole spécifique.

        Returns:
            Tuple[is_relevant, relevance_score]
        """
        symbol = symbol.upper()
        text_lower = text.lower()

        # Récupérer les entités pour ce symbole
        entities = self.config.symbol_entities.get(symbol, [])

        if not entities:
            # Symbole inconnu - considérer comme pertinent avec score moyen
            return True, 0.5

        # Compter les entités trouvées
        found = 0
        for entity in entities:
            if entity.lower() in text_lower:
                found += 1

        if found == 0:
            return False, 0.0

        # Score de pertinence
        relevance = min(1.0, found / max(1, len(entities)) + 0.3)
        return True, relevance

    def analyze_text(
        self,
        text: str,
        source: str = "other",
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyse le sentiment d'un texte unique.

        Returns:
            Dict avec score, confidence, level, source_weight, etc.
        """
        result = {
            "text": text[:100] + "..." if len(text) > 100 else text,
            "score": 0.0,
            "confidence": 0.0,
            "level": SentimentLevel.NEUTRAL.value,
            "source": source,
            "source_weight": self.get_source_weight(source),
            "keyword_boost": 0.0,
            "is_relevant": True,
            "relevance_score": 1.0,
            "weighted_score": 0.0,
            "method": "finbert" if self.config.use_finbert and FINBERT_AVAILABLE else "textblob"
        }

        if not text or len(text.strip()) < 10:
            return result

        # Vérifier le cache
        cached = self._check_cache(text)
        if cached:
            score, confidence = cached
        else:
            # Analyser avec FinBERT ou fallback
            score, confidence = self.finbert.analyze(text)
            self._set_cache(text, score, confidence)

        result["score"] = score
        result["confidence"] = confidence

        # Keyword boost
        boost = self.check_keyword_boost(text)
        result["keyword_boost"] = boost
        score += boost

        # Clamp le score
        score = max(-1.0, min(1.0, score))

        # Vérifier la pertinence pour le symbole
        if symbol:
            is_relevant, relevance = self.is_relevant_for_symbol(text, symbol)
            result["is_relevant"] = is_relevant
            result["relevance_score"] = relevance

            if not is_relevant:
                # Réduire fortement le poids si non pertinent
                result["source_weight"] *= 0.1

        # Score pondéré
        result["weighted_score"] = score * result["source_weight"] * result["relevance_score"]

        # Déterminer le niveau
        if score >= self.config.very_bullish_threshold:
            result["level"] = SentimentLevel.VERY_BULLISH.value
        elif score >= self.config.bullish_threshold:
            result["level"] = SentimentLevel.BULLISH.value
        elif score <= self.config.very_bearish_threshold:
            result["level"] = SentimentLevel.VERY_BEARISH.value
        elif score <= self.config.bearish_threshold:
            result["level"] = SentimentLevel.BEARISH.value
        else:
            result["level"] = SentimentLevel.NEUTRAL.value

        return result

    def analyze_news_batch(
        self,
        news_items: List[Dict[str, Any]],
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyse un batch de news et retourne un sentiment agrégé.

        Args:
            news_items: Liste de dicts avec 'title', 'source', optionnellement 'content'
            symbol: Symbole pour filtrage de pertinence

        Returns:
            Dict avec score agrégé, confidence, breakdown par source, etc.
        """
        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_items": len(news_items),
            "relevant_items": 0,
            "aggregate_score": 0.0,
            "aggregate_confidence": 0.0,
            "level": SentimentLevel.NEUTRAL.value,
            "signal": None,  # LONG, SHORT, ou None
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "source_breakdown": {},
            "top_bullish": [],
            "top_bearish": [],
            "details": []
        }

        if not news_items:
            return result

        total_weighted_score = 0.0
        total_weight = 0.0
        source_scores: Dict[str, List[float]] = {}

        for item in news_items:
            title = item.get("title", "")
            source = item.get("source", "other")
            content = item.get("content", "")

            # Analyser le titre (plus important)
            text = title
            if content:
                text += " " + content[:200]  # Ajouter un extrait du contenu

            analysis = self.analyze_text(text, source, symbol)
            result["details"].append(analysis)

            if analysis["is_relevant"]:
                result["relevant_items"] += 1

                # Accumuler pour la moyenne pondérée
                weight = analysis["source_weight"] * analysis["relevance_score"] * analysis["confidence"]
                total_weighted_score += analysis["score"] * weight
                total_weight += weight

                # Compteurs
                if analysis["level"] in [SentimentLevel.BULLISH.value, SentimentLevel.VERY_BULLISH.value]:
                    result["bullish_count"] += 1
                    result["top_bullish"].append({
                        "title": title[:80],
                        "source": source,
                        "score": analysis["score"]
                    })
                elif analysis["level"] in [SentimentLevel.BEARISH.value, SentimentLevel.VERY_BEARISH.value]:
                    result["bearish_count"] += 1
                    result["top_bearish"].append({
                        "title": title[:80],
                        "source": source,
                        "score": analysis["score"]
                    })
                else:
                    result["neutral_count"] += 1

                # Breakdown par source
                if source not in source_scores:
                    source_scores[source] = []
                source_scores[source].append(analysis["weighted_score"])

        # Calculer le score agrégé
        if total_weight > 0:
            result["aggregate_score"] = total_weighted_score / total_weight
            result["aggregate_confidence"] = min(1.0, total_weight / max(1, result["relevant_items"]))

        # Déterminer le niveau et signal
        agg_score = result["aggregate_score"]
        if agg_score >= self.config.very_bullish_threshold:
            result["level"] = SentimentLevel.VERY_BULLISH.value
            result["signal"] = "LONG"
        elif agg_score >= self.config.bullish_threshold:
            result["level"] = SentimentLevel.BULLISH.value
            result["signal"] = "LONG"
        elif agg_score <= self.config.very_bearish_threshold:
            result["level"] = SentimentLevel.VERY_BEARISH.value
            result["signal"] = "SHORT"
        elif agg_score <= self.config.bearish_threshold:
            result["level"] = SentimentLevel.BEARISH.value
            result["signal"] = "SHORT"
        else:
            result["level"] = SentimentLevel.NEUTRAL.value
            result["signal"] = None

        # Breakdown par source
        for source, scores in source_scores.items():
            result["source_breakdown"][source] = {
                "count": len(scores),
                "average_score": sum(scores) / len(scores) if scores else 0.0
            }

        # Trier top bullish/bearish
        result["top_bullish"] = sorted(
            result["top_bullish"],
            key=lambda x: x["score"],
            reverse=True
        )[:5]

        result["top_bearish"] = sorted(
            result["top_bearish"],
            key=lambda x: x["score"]
        )[:5]

        return result

    def get_trading_signal(
        self,
        news_items: List[Dict[str, Any]],
        symbol: str
    ) -> Dict[str, Any]:
        """
        Interface simplifiée pour obtenir un signal de trading basé sur le sentiment.

        Returns:
            Dict avec signal, score, confidence
        """
        analysis = self.analyze_news_batch(news_items, symbol)

        return {
            "signal": analysis["signal"],
            "score": analysis["aggregate_score"],
            "confidence": analysis["aggregate_confidence"],
            "level": analysis["level"],
            "bullish_count": analysis["bullish_count"],
            "bearish_count": analysis["bearish_count"],
            "relevant_items": analysis["relevant_items"],
            "top_bullish": analysis["top_bullish"][:3],
            "top_bearish": analysis["top_bearish"][:3],
        }


# =============================================================================
# INSTANCE GLOBALE ET FONCTIONS UTILITAIRES
# =============================================================================

_sentiment_analyzer: Optional[AdvancedSentimentAnalyzerV2] = None


def get_sentiment_analyzer(config: Optional[SentimentConfig] = None) -> AdvancedSentimentAnalyzerV2:
    """Récupère ou crée l'instance globale de l'analyseur de sentiment"""
    global _sentiment_analyzer

    if _sentiment_analyzer is None:
        _sentiment_analyzer = AdvancedSentimentAnalyzerV2(config)

    return _sentiment_analyzer


def analyze_sentiment_v2(
    text: str,
    source: str = "other",
    symbol: Optional[str] = None
) -> Dict[str, Any]:
    """Analyse le sentiment d'un texte unique"""
    analyzer = get_sentiment_analyzer()
    return analyzer.analyze_text(text, source, symbol)


def analyze_news_sentiment(
    news_items: List[Dict[str, Any]],
    symbol: str
) -> Dict[str, Any]:
    """Analyse le sentiment d'un batch de news pour un symbole"""
    analyzer = get_sentiment_analyzer()
    return analyzer.get_trading_signal(news_items, symbol)


def get_sentiment_signal(
    news_items: List[Dict[str, Any]],
    symbol: str
) -> Tuple[Optional[str], float, float]:
    """
    Interface rapide pour obtenir signal, score, confidence.

    Returns:
        Tuple[signal, score, confidence]
    """
    analyzer = get_sentiment_analyzer()
    result = analyzer.get_trading_signal(news_items, symbol)
    return result["signal"], result["score"], result["confidence"]
