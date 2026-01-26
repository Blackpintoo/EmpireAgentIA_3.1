#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOSS PATTERN ANALYZER - Analyse des patterns récurrents dans les pertes
CORRECTION AUDIT #3 - 2025-12-27

Ce module analyse les trades perdants pour identifier les patterns
récurrents et proposer des recommandations d'amélioration.

Patterns détectés:
1. AGAINST_HTF_TREND - Trade contre la tendance des timeframes supérieurs
2. LOW_SCORE - Score de signal < 7.5
3. LOW_CONFLUENCE - Confluence < 5
4. TOXIC_HOURS - Trade pendant les heures toxiques (0-5h, 22-23h)
5. NEAR_NEWS - Trade proche d'une annonce économique
6. HIGH_VOLATILITY - Trade pendant un régime volatile
7. POOR_RR - Ratio Risk/Reward défavorable
8. QUICK_REVERSAL - Reversal rapide après entrée

Usage:
    from utils.loss_pattern_analyzer import get_loss_analyzer

    analyzer = get_loss_analyzer()
    patterns = analyzer.analyze_loss(trade_info)
    report = analyzer.get_report()
"""

from __future__ import annotations

import csv
import json
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class LossPatternConfig:
    """Configuration de l'analyseur de patterns."""
    # Seuils pour les patterns
    min_score_threshold: float = 7.5
    min_confluence_threshold: int = 5
    toxic_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 22, 23])
    min_rr_threshold: float = 1.0
    quick_reversal_minutes: float = 15.0

    # Fichier d'historique
    history_file: str = "data/loss_patterns.csv"

    # Nombre max de patterns à conserver en mémoire
    max_history: int = 1000


@dataclass
class LossPattern:
    """Représente un pattern de perte identifié."""
    name: str
    frequency: int
    total_loss: float
    avg_loss: float
    conditions: Dict[str, Any]
    recommendation: str
    severity: str  # "high", "medium", "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "frequency": self.frequency,
            "total_loss": self.total_loss,
            "avg_loss": self.avg_loss,
            "conditions": self.conditions,
            "recommendation": self.recommendation,
            "severity": self.severity,
        }


# =============================================================================
# PATTERN DEFINITIONS
# =============================================================================

PATTERN_RECOMMENDATIONS = {
    "AGAINST_HTF_TREND": {
        "recommendation": "Renforcer le filtre MTF, exiger 100% alignment sur H4/D1",
        "severity": "high",
    },
    "LOW_SCORE": {
        "recommendation": "Augmenter min_score à 8.5 ou 9.0",
        "severity": "high",
    },
    "LOW_CONFLUENCE": {
        "recommendation": "Augmenter min_confluence à 6 ou plus",
        "severity": "high",
    },
    "TOXIC_HOURS": {
        "recommendation": "Élargir les heures bloquées ou réduire la taille de position",
        "severity": "medium",
    },
    "NEAR_NEWS": {
        "recommendation": "Augmenter le buffer news à 45-60 minutes avant/après",
        "severity": "medium",
    },
    "HIGH_VOLATILITY": {
        "recommendation": "Réduire la taille de position de 50% en régime volatile",
        "severity": "medium",
    },
    "POOR_RR": {
        "recommendation": "Exiger un R:R minimum de 1.5 avant d'entrer",
        "severity": "medium",
    },
    "QUICK_REVERSAL": {
        "recommendation": "Attendre une confirmation supplémentaire avant l'entrée",
        "severity": "low",
    },
    "SL_TOO_TIGHT": {
        "recommendation": "Utiliser le SL par invalidation de structure (compute_invalidation_sl)",
        "severity": "medium",
    },
    "OVERTRADING": {
        "recommendation": "Limiter à 3-5 trades par jour maximum",
        "severity": "low",
    },
}


# =============================================================================
# LOSS PATTERN ANALYZER
# =============================================================================

class LossPatternAnalyzer:
    """
    Analyse les trades perdants pour identifier les patterns récurrents.

    Cette classe:
    1. Détecte les patterns dans chaque trade perdant
    2. Agrège les statistiques par pattern
    3. Génère des recommandations d'amélioration
    4. Sauvegarde l'historique pour analyse
    """

    def __init__(self, config: Optional[LossPatternConfig] = None):
        self.config = config or LossPatternConfig()

        # Compteurs de patterns
        self.patterns: Dict[str, int] = defaultdict(int)
        self.losses_by_pattern: Dict[str, List[float]] = defaultdict(list)
        self.pattern_examples: Dict[str, List[Dict]] = defaultdict(list)

        # Historique des analyses
        self._analysis_history: List[Dict[str, Any]] = []

        # Thread safety
        self._lock = threading.Lock()

        # Stats globales
        self._total_losses_analyzed = 0
        self._total_loss_amount = 0.0

        # Charger l'historique si existant
        self._load_history()

        logger.info("[LOSS_ANALYZER] Initialisé")

    def _load_history(self) -> None:
        """Charge l'historique des patterns depuis le fichier."""
        history_path = Path(self.config.history_file)
        if not history_path.exists():
            return

        try:
            with open(history_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        pattern = row.get("pattern", "")
                        loss = float(row.get("loss", 0))
                        if pattern:
                            self.patterns[pattern] += 1
                            self.losses_by_pattern[pattern].append(loss)
                    except (ValueError, TypeError):
                        continue

            logger.debug(f"[LOSS_ANALYZER] Chargé {sum(self.patterns.values())} patterns historiques")

        except Exception as e:
            logger.warning(f"[LOSS_ANALYZER] Erreur chargement historique: {e}")

    def _save_analysis(self, trade_info: Dict[str, Any], patterns_found: List[str]) -> None:
        """Sauvegarde une analyse dans l'historique."""
        history_path = Path(self.config.history_file)

        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)

            file_exists = history_path.exists()

            with open(history_path, "a", encoding="utf-8", newline="") as f:
                fieldnames = [
                    "timestamp", "ticket", "symbol", "direction", "loss",
                    "pattern", "score", "confluence", "hour", "regime"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                for pattern in patterns_found:
                    writer.writerow({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ticket": trade_info.get("ticket", 0),
                        "symbol": trade_info.get("symbol", ""),
                        "direction": trade_info.get("direction", ""),
                        "loss": trade_info.get("pnl", 0),
                        "pattern": pattern,
                        "score": trade_info.get("score", 0),
                        "confluence": trade_info.get("confluence", 0),
                        "hour": trade_info.get("hour", 0),
                        "regime": trade_info.get("regime", ""),
                    })

        except Exception as e:
            logger.debug(f"[LOSS_ANALYZER] Erreur sauvegarde: {e}")

    def analyze_loss(self, trade_info: Dict[str, Any]) -> List[str]:
        """
        Analyse un trade perdant et identifie les patterns.

        Args:
            trade_info: Dict avec les informations du trade:
                - ticket: ID du trade
                - symbol: Symbole tradé
                - direction: "LONG" ou "SHORT"
                - pnl: Profit/Loss (négatif pour perte)
                - r_multiple: R-multiple du trade
                - hour: Heure de clôture (0-23)
                - duration_minutes: Durée du trade
                - mtf_aligned: True si aligné avec les TF supérieurs
                - score: Score du signal (0-10)
                - confluence: Score de confluence
                - regime: Régime de marché
                - news_nearby: True si proche d'une annonce

        Returns:
            Liste des patterns identifiés
        """
        pnl = trade_info.get("pnl", 0)

        # Ne pas analyser les trades gagnants
        if pnl >= 0:
            return []

        patterns_found: List[str] = []

        with self._lock:
            # Pattern 1: AGAINST_HTF_TREND
            mtf_aligned = trade_info.get("mtf_aligned", True)
            if not mtf_aligned:
                patterns_found.append("AGAINST_HTF_TREND")
                self.patterns["AGAINST_HTF_TREND"] += 1
                self.losses_by_pattern["AGAINST_HTF_TREND"].append(pnl)

            # Pattern 2: LOW_SCORE
            score = trade_info.get("score", 10)
            if score < self.config.min_score_threshold:
                patterns_found.append("LOW_SCORE")
                self.patterns["LOW_SCORE"] += 1
                self.losses_by_pattern["LOW_SCORE"].append(pnl)

            # Pattern 3: LOW_CONFLUENCE
            confluence = trade_info.get("confluence", 10)
            if confluence < self.config.min_confluence_threshold:
                patterns_found.append("LOW_CONFLUENCE")
                self.patterns["LOW_CONFLUENCE"] += 1
                self.losses_by_pattern["LOW_CONFLUENCE"].append(pnl)

            # Pattern 4: TOXIC_HOURS
            hour = trade_info.get("hour", 12)
            if hour in self.config.toxic_hours:
                patterns_found.append("TOXIC_HOURS")
                self.patterns["TOXIC_HOURS"] += 1
                self.losses_by_pattern["TOXIC_HOURS"].append(pnl)

            # Pattern 5: NEAR_NEWS
            news_nearby = trade_info.get("news_nearby", False)
            if news_nearby:
                patterns_found.append("NEAR_NEWS")
                self.patterns["NEAR_NEWS"] += 1
                self.losses_by_pattern["NEAR_NEWS"].append(pnl)

            # Pattern 6: HIGH_VOLATILITY
            regime = str(trade_info.get("regime", "")).lower()
            if regime == "volatile":
                patterns_found.append("HIGH_VOLATILITY")
                self.patterns["HIGH_VOLATILITY"] += 1
                self.losses_by_pattern["HIGH_VOLATILITY"].append(pnl)

            # Pattern 7: POOR_RR
            r_multiple = trade_info.get("r_multiple", 0)
            initial_rr = trade_info.get("initial_rr", 1.5)
            if initial_rr < self.config.min_rr_threshold:
                patterns_found.append("POOR_RR")
                self.patterns["POOR_RR"] += 1
                self.losses_by_pattern["POOR_RR"].append(pnl)

            # Pattern 8: QUICK_REVERSAL
            duration = trade_info.get("duration_minutes", 60)
            if duration < self.config.quick_reversal_minutes:
                patterns_found.append("QUICK_REVERSAL")
                self.patterns["QUICK_REVERSAL"] += 1
                self.losses_by_pattern["QUICK_REVERSAL"].append(pnl)

            # Pattern 9: SL_TOO_TIGHT (si SL touché rapidement)
            sl_touched = trade_info.get("sl_touched", False)
            if sl_touched and duration < 30:
                patterns_found.append("SL_TOO_TIGHT")
                self.patterns["SL_TOO_TIGHT"] += 1
                self.losses_by_pattern["SL_TOO_TIGHT"].append(pnl)

            # Mettre à jour les stats globales
            self._total_losses_analyzed += 1
            self._total_loss_amount += abs(pnl)

            # Stocker un exemple
            if patterns_found:
                example = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trade": trade_info,
                    "patterns": patterns_found,
                }
                for pattern in patterns_found:
                    if len(self.pattern_examples[pattern]) < 10:  # Max 10 exemples
                        self.pattern_examples[pattern].append(example)

        # Sauvegarder l'analyse
        if patterns_found:
            self._save_analysis(trade_info, patterns_found)

        return patterns_found

    def get_report(self) -> Dict[str, LossPattern]:
        """
        Génère un rapport des patterns de perte.

        Returns:
            Dict mapping pattern_name -> LossPattern
        """
        report = {}

        with self._lock:
            for pattern_name, count in self.patterns.items():
                losses = self.losses_by_pattern.get(pattern_name, [])
                total_loss = sum(abs(l) for l in losses)
                avg_loss = total_loss / len(losses) if losses else 0

                # Récupérer les infos du pattern
                pattern_info = PATTERN_RECOMMENDATIONS.get(pattern_name, {})

                report[pattern_name] = LossPattern(
                    name=pattern_name,
                    frequency=count,
                    total_loss=total_loss,
                    avg_loss=avg_loss,
                    conditions={},
                    recommendation=pattern_info.get("recommendation", "À analyser"),
                    severity=pattern_info.get("severity", "medium"),
                )

        return report

    def get_top_patterns(self, n: int = 5) -> List[LossPattern]:
        """
        Retourne les N patterns les plus impactants.

        Classement par impact = fréquence * perte moyenne

        Args:
            n: Nombre de patterns à retourner

        Returns:
            Liste des LossPattern triés par impact décroissant
        """
        report = self.get_report()

        # Trier par impact (fréquence * perte moyenne)
        sorted_patterns = sorted(
            report.values(),
            key=lambda p: p.frequency * p.avg_loss,
            reverse=True
        )

        return sorted_patterns[:n]

    def get_statistics(self) -> Dict[str, Any]:
        """Retourne les statistiques globales."""
        with self._lock:
            top_patterns = self.get_top_patterns(5)

            return {
                "total_losses_analyzed": self._total_losses_analyzed,
                "total_loss_amount": self._total_loss_amount,
                "unique_patterns": len(self.patterns),
                "pattern_counts": dict(self.patterns),
                "top_patterns": [p.to_dict() for p in top_patterns],
                "avg_loss_per_trade": (
                    self._total_loss_amount / self._total_losses_analyzed
                    if self._total_losses_analyzed > 0 else 0
                ),
            }

    def get_recommendations(self) -> List[Dict[str, Any]]:
        """
        Génère une liste de recommandations prioritaires.

        Returns:
            Liste de recommandations triées par priorité
        """
        top_patterns = self.get_top_patterns(5)

        recommendations = []
        for pattern in top_patterns:
            if pattern.frequency > 0:
                recommendations.append({
                    "pattern": pattern.name,
                    "priority": "high" if pattern.severity == "high" else "medium",
                    "frequency": pattern.frequency,
                    "avg_loss": pattern.avg_loss,
                    "recommendation": pattern.recommendation,
                    "expected_improvement": f"Réduction estimée: {pattern.frequency * pattern.avg_loss:.0f} USD",
                })

        return recommendations

    def reset(self) -> None:
        """Réinitialise les compteurs (pour tests)."""
        with self._lock:
            self.patterns.clear()
            self.losses_by_pattern.clear()
            self.pattern_examples.clear()
            self._total_losses_analyzed = 0
            self._total_loss_amount = 0.0

        logger.info("[LOSS_ANALYZER] Compteurs réinitialisés")


# =============================================================================
# INSTANCE GLOBALE
# =============================================================================

_analyzer: Optional[LossPatternAnalyzer] = None


def get_loss_analyzer(config: Optional[LossPatternConfig] = None) -> LossPatternAnalyzer:
    """Récupère ou crée l'instance globale de l'analyseur."""
    global _analyzer

    if _analyzer is None:
        _analyzer = LossPatternAnalyzer(config)

    return _analyzer


def analyze_trade_loss(trade_info: Dict[str, Any]) -> List[str]:
    """
    Fonction utilitaire pour analyser une perte.

    Usage:
        patterns = analyze_trade_loss({
            "ticket": 12345,
            "symbol": "BTCUSD",
            "pnl": -150.0,
            "score": 6.5,
            "confluence": 4,
            ...
        })
    """
    analyzer = get_loss_analyzer()
    return analyzer.analyze_loss(trade_info)


def get_loss_recommendations() -> List[Dict[str, Any]]:
    """Récupère les recommandations actuelles."""
    analyzer = get_loss_analyzer()
    return analyzer.get_recommendations()


__all__ = [
    "LossPatternAnalyzer",
    "LossPatternConfig",
    "LossPattern",
    "get_loss_analyzer",
    "analyze_trade_loss",
    "get_loss_recommendations",
    "PATTERN_RECOMMENDATIONS",
]
