#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRADE OUTCOME TRACKER - Suivi des résultats réels des trades
CORRECTION AUDIT #1 - 2025-12-27

Ce module surveille les positions MT5 et enregistre le P&L réel
dans le PerformanceTracker pour fermer la boucle de feedback.

Fonctionnalités:
1. Surveillance des positions MT5 (poll toutes les 30s)
2. Calcul du R-multiple réel à la clôture
3. Enregistrement automatique dans le PerformanceTracker
4. Historisation des trades dans data/trade_outcomes.csv

Usage:
    from utils.trade_outcome_tracker import start_outcome_tracking
    start_outcome_tracking()  # Démarre le worker en background
"""

from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.performance_tracker import default_tracker, PerformancePoint
    TRACKER_AVAILABLE = True
except ImportError:
    default_tracker = None
    PerformancePoint = None
    TRACKER_AVAILABLE = False

try:
    from utils.loss_pattern_analyzer import get_loss_analyzer
    LOSS_ANALYZER_AVAILABLE = True
except ImportError:
    get_loss_analyzer = None
    LOSS_ANALYZER_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OutcomeTrackerConfig:
    """Configuration du tracker de résultats."""
    poll_interval: float = 30.0          # Intervalle de poll en secondes
    history_file: str = "data/trade_outcomes.csv"
    max_history_days: int = 90           # Conserver 90 jours d'historique
    min_deal_profit_for_log: float = 0.0 # Logger tous les deals (même 0)
    enable_loss_analysis: bool = True    # Activer l'analyse des pertes


@dataclass
class TrackedPosition:
    """Représente une position suivie."""
    ticket: int
    symbol: str
    direction: str  # "LONG" ou "SHORT"
    volume: float
    price_open: float
    sl: float
    tp: float
    open_time: datetime
    magic: int
    comment: str
    initial_risk: float = 0.0  # Risque initial en USD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "price_open": self.price_open,
            "sl": self.sl,
            "tp": self.tp,
            "open_time": self.open_time.isoformat() if self.open_time else None,
            "magic": self.magic,
            "comment": self.comment,
            "initial_risk": self.initial_risk,
        }


@dataclass
class TradeOutcome:
    """Représente le résultat d'un trade clôturé."""
    ticket: int
    symbol: str
    direction: str
    profit: float
    r_multiple: float
    close_time: datetime
    duration_minutes: float
    entry_price: float
    exit_price: float
    volume: float
    commission: float = 0.0
    swap: float = 0.0
    exit_type: str = "unknown"  # "tp", "sl", "manual", "partial", "be", "trailing", "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction,
            "profit": self.profit,
            "r_multiple": self.r_multiple,
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "duration_minutes": self.duration_minutes,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "volume": self.volume,
            "commission": self.commission,
            "swap": self.swap,
            "exit_type": self.exit_type,
        }


# =============================================================================
# TRADE OUTCOME TRACKER
# =============================================================================

class TradeOutcomeTracker:
    """
    Surveille les trades MT5 et enregistre leur résultat réel.

    Cette classe:
    1. Détecte les nouvelles positions ouvertes
    2. Surveille leur fermeture
    3. Calcule le R-multiple réel
    4. Enregistre dans le PerformanceTracker
    5. Analyse les patterns de perte si activé
    """

    def __init__(self, config: Optional[OutcomeTrackerConfig] = None):
        self.config = config or OutcomeTrackerConfig()

        # État interne
        self._tracked_positions: Dict[int, TrackedPosition] = {}
        self._closed_tickets: Set[int] = set()
        self._outcomes: List[TradeOutcome] = []

        # Threading
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Stats de session
        self._session_start = datetime.now(timezone.utc)
        self._total_tracked = 0
        self._total_closed = 0
        self._total_profit = 0.0

        # Charger l'historique existant
        self._load_history()

        logger.info("[OUTCOME] TradeOutcomeTracker initialisé")

    def _load_history(self) -> None:
        """Charge l'historique des trades depuis le fichier CSV."""
        history_path = Path(self.config.history_file)
        if not history_path.exists():
            return

        try:
            # Lire les tickets déjà traités pour éviter les doublons
            with open(history_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ticket = int(row.get("ticket", 0))
                        if ticket > 0:
                            self._closed_tickets.add(ticket)
                    except (ValueError, TypeError):
                        continue

            logger.debug(f"[OUTCOME] Chargé {len(self._closed_tickets)} tickets historiques")
        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur chargement historique: {e}")

    def _save_outcome(self, outcome: TradeOutcome) -> None:
        """Sauvegarde un résultat dans le fichier CSV."""
        history_path = Path(self.config.history_file)

        try:
            # Créer le répertoire si nécessaire
            history_path.parent.mkdir(parents=True, exist_ok=True)

            # Vérifier si le fichier existe pour les headers
            file_exists = history_path.exists()

            with open(history_path, "a", encoding="utf-8", newline="") as f:
                fieldnames = [
                    "timestamp", "ticket", "symbol", "direction", "profit",
                    "r_multiple", "close_time", "duration_minutes", "entry_price",
                    "exit_price", "volume", "commission", "swap", "exit_type"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                row = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **outcome.to_dict()
                }
                writer.writerow(row)

        except Exception as e:
            logger.error(f"[OUTCOME] Erreur sauvegarde: {e}")

    def _get_open_positions(self) -> Dict[int, TrackedPosition]:
        """Récupère les positions ouvertes depuis MT5."""
        if not MT5_AVAILABLE or not mt5:
            return {}

        try:
            positions = mt5.positions_get()
            if positions is None:
                return {}

            result = {}
            for pos in positions:
                try:
                    ticket = pos.ticket
                    direction = "LONG" if pos.type == 0 else "SHORT"

                    # Calculer le risque initial (distance au SL)
                    initial_risk = 0.0
                    if pos.sl and pos.sl > 0:
                        sl_distance = abs(pos.price_open - pos.sl)
                        # Estimation du risque (simplifié)
                        initial_risk = sl_distance * pos.volume * 100  # Approximation

                    result[ticket] = TrackedPosition(
                        ticket=ticket,
                        symbol=pos.symbol,
                        direction=direction,
                        volume=pos.volume,
                        price_open=pos.price_open,
                        sl=pos.sl or 0.0,
                        tp=pos.tp or 0.0,
                        open_time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
                        magic=pos.magic,
                        comment=pos.comment or "",
                        initial_risk=initial_risk,
                    )
                except Exception as e:
                    logger.debug(f"[OUTCOME] Erreur parsing position: {e}")
                    continue

            return result

        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur récupération positions: {e}")
            return {}

    def _get_recent_deals(self, since_days: int = 1) -> List[Any]:
        """Récupère les deals récents depuis MT5."""
        if not MT5_AVAILABLE or not mt5:
            return []

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=since_days)

            deals = mt5.history_deals_get(start, now)
            return list(deals) if deals else []

        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur récupération deals: {e}")
            return []

    def _calculate_r_multiple(
        self,
        profit: float,
        initial_risk: float,
        sl_distance: float = 0.0,
        volume: float = 1.0
    ) -> float:
        """
        Calcule le R-multiple d'un trade.

        R = profit / risque_initial

        Si le risque initial n'est pas connu, on utilise une estimation
        basée sur la distance SL ou un risque par défaut.
        """
        # Utiliser le risque initial si disponible
        if initial_risk > 0:
            return profit / initial_risk

        # Sinon, estimer à partir de la distance SL
        if sl_distance > 0 and volume > 0:
            estimated_risk = sl_distance * volume * 100  # Approximation
            if estimated_risk > 0:
                return profit / estimated_risk

        # Fallback: considérer que le risque = |profit| en cas de perte
        if profit < 0:
            return -1.0  # Perte = -1R par défaut
        elif profit > 0:
            return 1.5  # Gain = +1.5R par défaut (estimation)

        return 0.0

    def _detect_exit_type(
        self,
        original: TrackedPosition,
        deal: Any,
        exit_price: float
    ) -> str:
        """
        Détecte le type de sortie d'un trade.

        Types possibles:
        - "tp": Take Profit atteint
        - "sl": Stop Loss atteint
        - "be": Break Even (SL déplacé à l'entrée)
        - "trailing": Trailing Stop
        - "partial": Fermeture partielle
        - "manual": Fermeture manuelle par le trader
        - "unknown": Impossible à déterminer

        Logique de détection:
        1. Si le commentaire contient "tp" ou prix == TP → TP
        2. Si le commentaire contient "sl" ou prix == SL → SL
        3. Si le volume du deal < volume original → Partial
        4. Si prix proche de l'entrée et profit ~0 → BE
        5. Si aucune des conditions ci-dessus → MANUAL
        """
        try:
            comment = (getattr(deal, "comment", "") or "").lower()
            reason = getattr(deal, "reason", -1)  # MT5 deal reason

            # MT5 Deal Reasons (constantes)
            # DEAL_REASON_CLIENT = 0  # Fermeture manuelle
            # DEAL_REASON_MOBILE = 1  # Mobile
            # DEAL_REASON_WEB = 2     # Web
            # DEAL_REASON_EXPERT = 3  # Expert Advisor (bot)
            # DEAL_REASON_SL = 4      # Stop Loss
            # DEAL_REASON_TP = 5      # Take Profit
            # DEAL_REASON_SO = 6      # Stop Out (margin)
            # DEAL_REASON_ROLLOVER = 7
            # DEAL_REASON_VMARGIN = 8

            # 1. Vérifier via la raison MT5 (plus fiable)
            if reason == 5:  # DEAL_REASON_TP
                return "tp"
            if reason == 4:  # DEAL_REASON_SL
                # Différencier SL normal, BE et trailing
                if original.sl > 0:
                    sl_vs_entry = abs(original.sl - original.price_open)
                    # Si SL très proche de l'entrée → probablement BE
                    tolerance = original.price_open * 0.0005  # 0.05% de tolérance
                    if sl_vs_entry < tolerance:
                        return "be"
                    # Si SL au-delà de l'entrée (profit) → trailing
                    if original.direction == "LONG" and original.sl > original.price_open:
                        return "trailing"
                    if original.direction == "SHORT" and original.sl < original.price_open:
                        return "trailing"
                return "sl"

            # 2. Fermeture manuelle (client, mobile, web)
            if reason in (0, 1, 2):
                return "manual"

            # 3. Vérifier le commentaire du deal
            if "tp" in comment or "take" in comment or "profit" in comment:
                return "tp"
            if "sl" in comment or "stop" in comment:
                return "sl"
            if "partial" in comment or "close_pct" in comment:
                return "partial"
            if "be" in comment or "breakeven" in comment:
                return "be"
            if "trail" in comment:
                return "trailing"
            if "manual" in comment:
                return "manual"

            # 4. Vérifier si c'est une fermeture partielle (volume)
            deal_volume = getattr(deal, "volume", 0)
            if deal_volume > 0 and deal_volume < original.volume * 0.95:
                return "partial"

            # 5. Vérifier le prix vs TP/SL
            if original.tp > 0:
                tp_tolerance = abs(original.tp - original.price_open) * 0.02  # 2% de marge
                if abs(exit_price - original.tp) < tp_tolerance:
                    return "tp"

            if original.sl > 0:
                sl_tolerance = abs(original.sl - original.price_open) * 0.02  # 2% de marge
                if abs(exit_price - original.sl) < sl_tolerance:
                    return "sl"

            # 6. Si reason == 3 (Expert) mais pas TP/SL → le bot a fermé manuellement
            if reason == 3:
                # Vérifier si c'est un trailing stop qui a été touché
                # en analysant si le prix est meilleur que l'entrée
                if original.direction == "LONG" and exit_price > original.price_open:
                    return "trailing"
                if original.direction == "SHORT" and exit_price < original.price_open:
                    return "trailing"
                return "manual"  # Le bot a fermé manuellement

            # 7. Par défaut, si on ne peut pas déterminer
            # Si profitable sans TP → probablement manuel
            # Si perdant sans SL → probablement manuel
            return "manual"

        except Exception as e:
            logger.debug(f"[OUTCOME] Erreur détection exit_type: {e}")
            return "unknown"

    def _process_closed_position(
        self,
        original: TrackedPosition,
        deal: Any
    ) -> Optional[TradeOutcome]:
        """Traite une position fermée et crée l'outcome."""
        try:
            profit = deal.profit
            commission = getattr(deal, "commission", 0.0) or 0.0
            swap = getattr(deal, "swap", 0.0) or 0.0

            # Profit net
            net_profit = profit + commission + swap

            # Calculer le R-multiple
            sl_distance = abs(original.price_open - original.sl) if original.sl > 0 else 0
            r_multiple = self._calculate_r_multiple(
                profit=net_profit,
                initial_risk=original.initial_risk,
                sl_distance=sl_distance,
                volume=original.volume
            )

            # Durée du trade
            close_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
            duration = (close_time - original.open_time).total_seconds() / 60.0

            # Détecter le type de sortie
            exit_price = deal.price
            exit_type = self._detect_exit_type(original, deal, exit_price)

            outcome = TradeOutcome(
                ticket=original.ticket,
                symbol=original.symbol,
                direction=original.direction,
                profit=net_profit,
                r_multiple=r_multiple,
                close_time=close_time,
                duration_minutes=duration,
                entry_price=original.price_open,
                exit_price=exit_price,
                volume=original.volume,
                commission=commission,
                swap=swap,
                exit_type=exit_type,
            )

            return outcome

        except Exception as e:
            logger.error(f"[OUTCOME] Erreur traitement position fermée: {e}")
            return None

    def _record_to_performance_tracker(self, outcome: TradeOutcome, original: TrackedPosition) -> None:
        """Enregistre le résultat dans le PerformanceTracker."""
        if not TRACKER_AVAILABLE or not default_tracker:
            logger.debug("[OUTCOME] PerformanceTracker non disponible")
            return

        try:
            # Extraire le timeframe et l'agent du commentaire si possible
            comment = original.comment or ""
            timeframe = "M30"  # Défaut
            agent = "unknown"

            # Parser le commentaire (format attendu: "agent:structure|tf:H1|...")
            parts = comment.split("|")
            for part in parts:
                if ":" in part:
                    key, value = part.split(":", 1)
                    if key.lower() == "agent":
                        agent = value.lower()
                    elif key.lower() in ("tf", "timeframe"):
                        timeframe = value.upper()

            # Créer le point de performance
            point = PerformancePoint(
                symbol=original.symbol,
                agent=agent,
                timeframe=timeframe,
                regime="default",  # Pourrait être enrichi
                score=0.5,  # Score neutre pour les résultats
                outcome=outcome.r_multiple,
                executed=True,
            )

            # Enregistrer
            default_tracker().record(point)

            logger.debug(
                f"[OUTCOME] Enregistré dans tracker: {original.symbol} "
                f"agent={agent} R={outcome.r_multiple:.2f}"
            )

        except Exception as e:
            logger.error(f"[OUTCOME] Erreur enregistrement tracker: {e}")

    def _analyze_loss_pattern(self, outcome: TradeOutcome, original: TrackedPosition) -> None:
        """Analyse le pattern de perte si le trade est perdant."""
        if not self.config.enable_loss_analysis:
            return

        if outcome.profit >= 0:
            return  # Pas une perte

        if not LOSS_ANALYZER_AVAILABLE or not get_loss_analyzer:
            return

        try:
            analyzer = get_loss_analyzer()

            # Construire les infos du trade pour l'analyse
            trade_info = {
                "ticket": outcome.ticket,
                "symbol": outcome.symbol,
                "direction": outcome.direction,
                "pnl": outcome.profit,
                "r_multiple": outcome.r_multiple,
                "hour": outcome.close_time.hour if outcome.close_time else 12,
                "duration_minutes": outcome.duration_minutes,
                # Ces champs seraient enrichis par l'orchestrateur si disponibles
                "mtf_aligned": True,  # Par défaut, à enrichir
                "score": 8.0,  # Par défaut, à enrichir
                "confluence": 5,  # Par défaut, à enrichir
                "regime": "default",  # Par défaut, à enrichir
                "news_nearby": False,  # Par défaut, à enrichir
            }

            patterns = analyzer.analyze_loss(trade_info)

            if patterns:
                logger.info(
                    f"[OUTCOME] Patterns de perte détectés pour {outcome.ticket}: "
                    f"{', '.join(patterns)}"
                )

        except Exception as e:
            logger.debug(f"[OUTCOME] Erreur analyse perte: {e}")

    def _poll_and_update(self) -> None:
        """Boucle principale de surveillance."""
        logger.info("[OUTCOME] Démarrage de la boucle de surveillance")

        while self._running:
            try:
                # 1. Récupérer les positions actuelles
                current_positions = self._get_open_positions()

                with self._lock:
                    # 2. Détecter les nouvelles positions
                    for ticket, pos in current_positions.items():
                        if ticket not in self._tracked_positions:
                            self._tracked_positions[ticket] = pos
                            self._total_tracked += 1
                            logger.info(
                                f"[OUTCOME] Nouvelle position trackée: #{ticket} "
                                f"{pos.symbol} {pos.direction} {pos.volume} lots"
                            )

                    # 3. Détecter les positions fermées
                    tracked_tickets = set(self._tracked_positions.keys())
                    current_tickets = set(current_positions.keys())
                    closed_tickets = tracked_tickets - current_tickets

                    for ticket in closed_tickets:
                        if ticket in self._closed_tickets:
                            # Déjà traité
                            if ticket in self._tracked_positions:
                                del self._tracked_positions[ticket]
                            continue

                        original = self._tracked_positions.get(ticket)
                        if not original:
                            continue

                        # Chercher le deal de clôture
                        deals = self._get_recent_deals(since_days=1)
                        deal_found = False

                        for deal in deals:
                            # DEAL_ENTRY_OUT = 1 (clôture)
                            if deal.position_id == ticket and deal.entry == 1:
                                outcome = self._process_closed_position(original, deal)

                                if outcome:
                                    # Enregistrer
                                    self._outcomes.append(outcome)
                                    self._save_outcome(outcome)
                                    self._record_to_performance_tracker(outcome, original)
                                    self._analyze_loss_pattern(outcome, original)

                                    self._closed_tickets.add(ticket)
                                    self._total_closed += 1
                                    self._total_profit += outcome.profit

                                    # Emoji par type de sortie pour logs lisibles
                                    exit_emoji = {
                                        "tp": "🎯", "sl": "🛑", "be": "⚖️",
                                        "trailing": "📈", "partial": "✂️",
                                        "manual": "👆", "unknown": "❓"
                                    }.get(outcome.exit_type, "❓")

                                    logger.info(
                                        f"[OUTCOME] Trade clôturé: #{ticket} {original.symbol} "
                                        f"{exit_emoji} {outcome.exit_type.upper()} "
                                        f"P&L={outcome.profit:.2f} R={outcome.r_multiple:.2f} "
                                        f"Durée={outcome.duration_minutes:.0f}min"
                                    )

                                    deal_found = True
                                break

                        if not deal_found:
                            logger.debug(f"[OUTCOME] Deal non trouvé pour #{ticket}")

                        # Nettoyer
                        del self._tracked_positions[ticket]

            except Exception as e:
                logger.warning(f"[OUTCOME] Erreur dans la boucle: {e}")

            # Attendre avant le prochain poll
            time.sleep(self.config.poll_interval)

        logger.info("[OUTCOME] Boucle de surveillance arrêtée")

    def start(self) -> None:
        """Démarre le worker de surveillance."""
        if self._running:
            logger.warning("[OUTCOME] Worker déjà en cours d'exécution")
            return

        if not MT5_AVAILABLE:
            logger.warning("[OUTCOME] MT5 non disponible - mode dégradé")
            # On démarre quand même pour logger

        self._running = True
        self._session_start = datetime.now(timezone.utc)
        self._thread = threading.Thread(
            target=self._poll_and_update,
            name="trade-outcome-tracker",
            daemon=True
        )
        self._thread.start()
        logger.info("[OUTCOME] Trade Outcome Tracker démarré")

    def stop(self) -> None:
        """Arrête le worker de surveillance."""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

        logger.info(
            f"[OUTCOME] Trade Outcome Tracker arrêté - "
            f"Session: {self._total_tracked} trackés, {self._total_closed} clôturés, "
            f"P&L total: {self._total_profit:.2f}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de la session."""
        with self._lock:
            return {
                "session_start": self._session_start.isoformat(),
                "running": self._running,
                "positions_tracked": len(self._tracked_positions),
                "total_tracked": self._total_tracked,
                "total_closed": self._total_closed,
                "total_profit": self._total_profit,
                "closed_tickets_count": len(self._closed_tickets),
            }

    def get_recent_outcomes(self, n: int = 10) -> List[Dict[str, Any]]:
        """Retourne les N derniers résultats."""
        with self._lock:
            return [o.to_dict() for o in self._outcomes[-n:]]


# =============================================================================
# INSTANCE GLOBALE ET FONCTIONS UTILITAIRES
# =============================================================================

_outcome_tracker: Optional[TradeOutcomeTracker] = None


def get_outcome_tracker(config: Optional[OutcomeTrackerConfig] = None) -> TradeOutcomeTracker:
    """Récupère ou crée l'instance globale du tracker."""
    global _outcome_tracker

    if _outcome_tracker is None:
        _outcome_tracker = TradeOutcomeTracker(config)

    return _outcome_tracker


def start_outcome_tracking(config: Optional[OutcomeTrackerConfig] = None) -> TradeOutcomeTracker:
    """
    Démarre le tracking des résultats de trades.

    Usage:
        from utils.trade_outcome_tracker import start_outcome_tracking
        start_outcome_tracking()  # Démarre en background
    """
    tracker = get_outcome_tracker(config)
    tracker.start()
    return tracker


def stop_outcome_tracking() -> None:
    """Arrête le tracking des résultats."""
    global _outcome_tracker

    if _outcome_tracker:
        _outcome_tracker.stop()


def get_outcome_stats() -> Dict[str, Any]:
    """Récupère les statistiques du tracker."""
    tracker = get_outcome_tracker()
    return tracker.get_stats()


__all__ = [
    "TradeOutcomeTracker",
    "OutcomeTrackerConfig",
    "TrackedPosition",
    "TradeOutcome",
    "get_outcome_tracker",
    "start_outcome_tracking",
    "stop_outcome_tracking",
    "get_outcome_stats",
]
