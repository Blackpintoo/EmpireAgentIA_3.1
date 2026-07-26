#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRADE OUTCOME TRACKER - Suivi des résultats réels des trades
CORRECTION AUDIT #1 - 2025-12-27
FIX 2026-03-01 - R-multiple corrigé, fermetures partielles, sync pm_state

Ce module surveille les positions MT5 et enregistre le P&L réel
dans le PerformanceTracker pour fermer la boucle de feedback.

Fonctionnalités:
1. Surveillance des positions MT5 (poll toutes les 30s)
2. Calcul du R-multiple réel à la clôture (avec initial_risk fiable)
3. Gestion des fermetures partielles (agrégation PnL par ticket)
4. Enregistrement automatique dans le PerformanceTracker
5. Historisation des trades dans data/trade_outcomes.csv
6. Synchronisation avec pm_state.json pour détecter les partiels

Usage:
    from utils.trade_outcome_tracker import start_outcome_tracking
    start_outcome_tracking()  # Démarre le worker en background
"""

from __future__ import annotations

import csv
import json
import os
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
    from utils.performance_tracker import default_tracker, get_tracker_for_symbol, PerformancePoint
    TRACKER_AVAILABLE = True
except ImportError:
    default_tracker = None
    get_tracker_for_symbol = None
    PerformancePoint = None
    TRACKER_AVAILABLE = False

try:
    from utils.loss_pattern_analyzer import get_loss_analyzer
    LOSS_ANALYZER_AVAILABLE = True
except ImportError:
    get_loss_analyzer = None
    LOSS_ANALYZER_AVAILABLE = False


# Sentinel value for unknown R-multiple
R_UNKNOWN = "R_UNKNOWN"

# Path to pm_state.json (shared with position_manager.py)
_PM_STATE_PATH = os.path.join("data", "pm_state.json")


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
    initial_risk: float = 0.0  # Risque initial en USD (calculé via MT5 symbol_info)
    initial_volume: float = 0.0  # Volume initial (avant partiels)

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
            "initial_volume": self.initial_volume,
        }


@dataclass
class TradeOutcome:
    """Représente le résultat d'un trade clôturé."""
    ticket: int
    symbol: str
    direction: str
    profit: float
    r_multiple: Any  # float ou "R_UNKNOWN"
    close_time: datetime
    duration_minutes: float
    entry_price: float
    exit_price: float
    volume: float
    commission: float = 0.0
    swap: float = 0.0
    exit_type: str = "unknown"  # "tp", "sl", "manual", "partial", "be", "trailing", "unknown"
    partial_deals: str = ""     # JSON list of partial deal info [{deal_id, volume, profit, price}]

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
            "partial_deals": self.partial_deals,
        }


# =============================================================================
# HELPERS
# =============================================================================

def _get_point_value(symbol: str) -> float:
    """
    Récupère la valeur d'un point (en devise du compte) depuis MT5 symbol_info.

    Utilise trade_tick_value / trade_tick_size pour un calcul précis.
    Fallback : 1.0 si MT5 indisponible.
    """
    if not MT5_AVAILABLE or not mt5:
        return 1.0
    try:
        info = mt5.symbol_info(symbol)
        if info:
            tick_size = getattr(info, "trade_tick_size", 0)
            tick_value = getattr(info, "trade_tick_value", 0)
            if tick_size > 0 and tick_value > 0:
                return tick_value / tick_size
    except Exception:
        pass
    return 1.0


def _read_pm_state() -> Dict[str, Any]:
    """Lit pm_state.json (read-only, pas de lock — on tolère les lectures obsolètes)."""
    try:
        if os.path.exists(_PM_STATE_PATH):
            with open(_PM_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return {}


def _get_pm_partial_deals(symbol: str, ticket: int) -> List[int]:
    """
    Retourne la liste des deal_tickets enregistrés par PM pour les fermetures
    partielles de ce ticket.
    """
    pm = _read_pm_state()
    key = f"{symbol}:{ticket}"
    entry = pm.get(key, {})
    return entry.get("partial_deal_tickets", [])


# =============================================================================
# TRADE OUTCOME TRACKER
# =============================================================================

class TradeOutcomeTracker:
    """
    Surveille les trades MT5 et enregistre leur résultat réel.

    Cette classe:
    1. Détecte les nouvelles positions ouvertes
    2. Surveille leur fermeture (complète et partielle)
    3. Calcule le R-multiple réel (initial_risk via MT5 ou R_UNKNOWN)
    4. Agrège les PnL des fermetures partielles par ticket
    5. Enregistre dans le PerformanceTracker
    6. Analyse les patterns de perte si activé
    """

    def __init__(self, config: Optional[OutcomeTrackerConfig] = None):
        self.config = config or OutcomeTrackerConfig()

        # État interne
        self._tracked_positions: Dict[int, TrackedPosition] = {}
        self._closed_tickets: Set[int] = set()
        self._processed_deal_ids: Set[int] = set()  # deal IDs déjà traités (anti-doublon)
        self._outcomes: List[TradeOutcome] = []

        # Agrégation des fermetures partielles par ticket
        # {ticket: {"deals": [...], "total_profit": float, "total_commission": float, ...}}
        self._partial_aggregation: Dict[int, Dict[str, Any]] = {}

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
            history_path.parent.mkdir(parents=True, exist_ok=True)

            file_exists = history_path.exists()

            with open(history_path, "a", encoding="utf-8", newline="") as f:
                fieldnames = [
                    "timestamp", "ticket", "symbol", "direction", "profit",
                    "r_multiple", "close_time", "duration_minutes", "entry_price",
                    "exit_price", "volume", "commission", "swap", "exit_type",
                    "partial_deals"
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
                    symbol = pos.symbol

                    # Calculer le risque initial avec point_value réel
                    initial_risk = 0.0
                    if pos.sl and pos.sl > 0:
                        sl_distance = abs(pos.price_open - pos.sl)
                        point_value = _get_point_value(symbol)
                        initial_risk = sl_distance * pos.volume * point_value

                    result[ticket] = TrackedPosition(
                        ticket=ticket,
                        symbol=symbol,
                        direction=direction,
                        volume=pos.volume,
                        price_open=pos.price_open,
                        sl=pos.sl or 0.0,
                        tp=pos.tp or 0.0,
                        open_time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
                        magic=pos.magic,
                        comment=pos.comment or "",
                        initial_risk=initial_risk,
                        initial_volume=pos.volume,
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

    # =========================================================================
    # R-MULTIPLE CALCULATION (FIX 2026-03-01)
    # =========================================================================

    def _calculate_r_multiple(
        self,
        profit: float,
        initial_risk: float,
        sl_distance: float = 0.0,
        volume: float = 1.0,
        symbol: str = "",
    ) -> Any:
        """
        Calcule le R-multiple d'un trade.

        R = profit / risque_initial

        Priorité :
          1. initial_risk pré-calculé (depuis TrackedPosition, basé sur MT5 symbol_info)
          2. Recalcul depuis SL : abs(entry-sl) * volume * point_value
          3. R_UNKNOWN si ni l'un ni l'autre disponible

        Returns:
            float si calculable, ou "R_UNKNOWN" si impossible.
        """
        # Priorité 1 : initial_risk déjà calculé (via _get_open_positions)
        if initial_risk > 0:
            return profit / initial_risk

        # Priorité 2 : recalcul depuis SL distance + point_value MT5
        if sl_distance > 0 and volume > 0:
            point_value = _get_point_value(symbol) if symbol else 1.0
            estimated_risk = sl_distance * volume * point_value
            if estimated_risk > 0:
                return profit / estimated_risk

        # Priorité 3 : impossible de calculer → R_UNKNOWN
        logger.debug(
            f"[OUTCOME] R_UNKNOWN pour {symbol}: initial_risk={initial_risk}, "
            f"sl_distance={sl_distance}, volume={volume}"
        )
        return R_UNKNOWN

    # =========================================================================
    # EXIT TYPE DETECTION
    # =========================================================================

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

            # 1. Vérifier via la raison MT5 (plus fiable)
            if reason == 5:  # DEAL_REASON_TP
                return "tp"
            if reason == 4:  # DEAL_REASON_SL
                # Différencier SL normal, BE et trailing
                if original.sl > 0:
                    sl_vs_entry = abs(original.sl - original.price_open)
                    tolerance = original.price_open * 0.0005  # 0.05% de tolérance
                    if sl_vs_entry < tolerance:
                        return "be"
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
            if deal_volume > 0 and deal_volume < original.initial_volume * 0.95:
                return "partial"

            # 5. Vérifier le prix vs TP/SL
            if original.tp > 0:
                tp_tolerance = abs(original.tp - original.price_open) * 0.02
                if abs(exit_price - original.tp) < tp_tolerance:
                    return "tp"

            if original.sl > 0:
                sl_tolerance = abs(original.sl - original.price_open) * 0.02
                if abs(exit_price - original.sl) < sl_tolerance:
                    return "sl"

            # 6. Si reason == 3 (Expert) mais pas TP/SL → le bot a fermé
            if reason == 3:
                if original.direction == "LONG" and exit_price > original.price_open:
                    return "trailing"
                if original.direction == "SHORT" and exit_price < original.price_open:
                    return "trailing"
                return "manual"

            return "manual"

        except Exception as e:
            logger.debug(f"[OUTCOME] Erreur détection exit_type: {e}")
            return "unknown"

    # =========================================================================
    # PARTIAL CLOSE AGGREGATION (FIX 2026-03-01)
    # =========================================================================

    def _get_closing_deals_for_ticket(self, ticket: int, deals: List[Any]) -> List[Any]:
        """Retourne tous les deals de clôture (entry==1) pour un ticket donné."""
        closing = []
        for deal in deals:
            try:
                if (getattr(deal, "position_id", 0) == ticket
                        and getattr(deal, "entry", 0) == 1):
                    closing.append(deal)
            except Exception:
                continue
        return closing

    def _is_position_fully_closed(
        self, ticket: int, current_positions: Dict[int, TrackedPosition]
    ) -> bool:
        """Vérifie si une position est entièrement fermée (absent des positions ouvertes)."""
        return ticket not in current_positions

    def _aggregate_partial_deals(
        self, original: TrackedPosition, closing_deals: List[Any]
    ) -> Optional[TradeOutcome]:
        """
        Agrège tous les deals partiels d'un ticket en un seul TradeOutcome.

        Ne retourne un résultat que quand la position est entièrement fermée
        (tous les deals partiels collectés).

        Returns:
            TradeOutcome agrégé, ou None si erreur.
        """
        if not closing_deals:
            return None

        try:
            total_profit = 0.0
            total_commission = 0.0
            total_swap = 0.0
            total_volume_closed = 0.0
            last_close_time = None
            last_exit_price = 0.0
            partial_info: List[Dict[str, Any]] = []

            for deal in closing_deals:
                deal_id = getattr(deal, "ticket", getattr(deal, "order", 0))

                # Anti-doublon : skip si déjà traité
                if deal_id in self._processed_deal_ids:
                    continue

                d_profit = getattr(deal, "profit", 0.0) or 0.0
                d_commission = getattr(deal, "commission", 0.0) or 0.0
                d_swap = getattr(deal, "swap", 0.0) or 0.0
                d_volume = getattr(deal, "volume", 0.0) or 0.0
                d_price = getattr(deal, "price", 0.0) or 0.0
                d_time = getattr(deal, "time", 0)

                total_profit += d_profit
                total_commission += d_commission
                total_swap += d_swap
                total_volume_closed += d_volume
                last_exit_price = d_price

                if d_time:
                    dt = datetime.fromtimestamp(d_time, tz=timezone.utc)
                    if last_close_time is None or dt > last_close_time:
                        last_close_time = dt

                partial_info.append({
                    "deal_id": deal_id,
                    "volume": round(d_volume, 4),
                    "profit": round(d_profit, 2),
                    "price": d_price,
                })

                self._processed_deal_ids.add(deal_id)

            if not partial_info:
                return None  # Tous les deals étaient déjà traités

            # Profit net total
            net_profit = total_profit + total_commission + total_swap

            # Calculer le R-multiple sur le profit agrégé
            sl_distance = abs(original.price_open - original.sl) if original.sl > 0 else 0
            r_multiple = self._calculate_r_multiple(
                profit=net_profit,
                initial_risk=original.initial_risk,
                sl_distance=sl_distance,
                volume=original.initial_volume,  # Volume initial, pas le volume partiel
                symbol=original.symbol,
            )

            # Durée totale (de l'ouverture au dernier close)
            if last_close_time and original.open_time:
                duration = (last_close_time - original.open_time).total_seconds() / 60.0
            else:
                duration = 0.0

            # Détecter le type de sortie du dernier deal
            last_deal = closing_deals[-1]
            exit_type = self._detect_exit_type(original, last_deal, last_exit_price)

            # Si c'était un mix de partiels, le mentionner
            if len(closing_deals) > 1:
                exit_type = f"{exit_type}+partial"

            outcome = TradeOutcome(
                ticket=original.ticket,
                symbol=original.symbol,
                direction=original.direction,
                profit=net_profit,
                r_multiple=r_multiple,
                close_time=last_close_time or datetime.now(timezone.utc),
                duration_minutes=duration,
                entry_price=original.price_open,
                exit_price=last_exit_price,
                volume=original.initial_volume,
                commission=total_commission,
                swap=total_swap,
                exit_type=exit_type,
                partial_deals=json.dumps(partial_info, ensure_ascii=False),
            )

            return outcome

        except Exception as e:
            logger.error(f"[OUTCOME] Erreur agrégation partiels #{original.ticket}: {e}")
            return None

    # =========================================================================
    # MAIN PROCESSING
    # =========================================================================

    def _process_closed_position(
        self,
        original: TrackedPosition,
        deal: Any
    ) -> Optional[TradeOutcome]:
        """Traite une position fermée (deal unique, pas de partiels)."""
        try:
            deal_id = getattr(deal, "ticket", getattr(deal, "order", 0))

            # Anti-doublon
            if deal_id in self._processed_deal_ids:
                return None
            self._processed_deal_ids.add(deal_id)

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
                volume=original.initial_volume,
                symbol=original.symbol,
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
                volume=original.initial_volume,
                commission=commission,
                swap=swap,
                exit_type=exit_type,
                partial_deals="",
            )

            return outcome

        except Exception as e:
            logger.error(f"[OUTCOME] Erreur traitement position fermée: {e}")
            return None

    def _record_to_performance_tracker(self, outcome: TradeOutcome, original: TrackedPosition) -> None:
        """
        Enregistre le résultat dans le PerformanceTracker.

        FIX 2026-03-01: NE PAS enregistrer si r_multiple == R_UNKNOWN.
        """
        if outcome.r_multiple == R_UNKNOWN:
            logger.info(
                f"[OUTCOME] R_UNKNOWN pour #{outcome.ticket} {outcome.symbol} "
                f"— non enregistré dans PerformanceTracker"
            )
            return

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
                regime="default",
                score=0.5,
                outcome=outcome.r_multiple,
                executed=True,
            )

            # Enregistrer dans le tracker per-symbol
            tracker_fn = get_tracker_for_symbol or default_tracker
            tracker_fn(original.symbol).record(point)

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

            # Utiliser le r_multiple numérique ou -1 si R_UNKNOWN
            r_mult = outcome.r_multiple if outcome.r_multiple != R_UNKNOWN else -1.0

            trade_info = {
                "ticket": outcome.ticket,
                "symbol": outcome.symbol,
                "direction": outcome.direction,
                "pnl": outcome.profit,
                "r_multiple": r_mult,
                "hour": outcome.close_time.hour if outcome.close_time else 12,
                "duration_minutes": outcome.duration_minutes,
                "mtf_aligned": True,
                "score": 8.0,
                "confluence": 5,
                "regime": "default",
                "news_nearby": False,
            }

            patterns = analyzer.analyze_loss(trade_info)

            if patterns:
                logger.info(
                    f"[OUTCOME] Patterns de perte détectés pour {outcome.ticket}: "
                    f"{', '.join(patterns)}"
                )

        except Exception as e:
            logger.debug(f"[OUTCOME] Erreur analyse perte: {e}")

    # =========================================================================
    # POLL LOOP
    # =========================================================================

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
                                f"{pos.symbol} {pos.direction} {pos.volume} lots "
                                f"risk={pos.initial_risk:.2f}"
                            )

                    # 3. Mettre à jour le volume courant des positions trackées
                    # (le volume diminue après un partial close dans MT5)
                    for ticket, pos in current_positions.items():
                        if ticket in self._tracked_positions:
                            tracked = self._tracked_positions[ticket]
                            # Conserver initial_volume et initial_risk d'origine
                            # mais mettre à jour volume courant pour la détection
                            tracked.volume = pos.volume

                    # 4. Détecter les positions fermées
                    tracked_tickets = set(self._tracked_positions.keys())
                    current_tickets = set(current_positions.keys())
                    closed_tickets = tracked_tickets - current_tickets

                    for ticket in closed_tickets:
                        if ticket in self._closed_tickets:
                            if ticket in self._tracked_positions:
                                del self._tracked_positions[ticket]
                            continue

                        original = self._tracked_positions.get(ticket)
                        if not original:
                            continue

                        # Chercher TOUS les deals de clôture pour ce ticket
                        deals = self._get_recent_deals(since_days=2)
                        closing_deals = self._get_closing_deals_for_ticket(ticket, deals)

                        if not closing_deals:
                            logger.debug(f"[OUTCOME] Deal non trouvé pour #{ticket}")
                            del self._tracked_positions[ticket]
                            continue

                        # Vérifier les deal_tickets connus de PM pour enrichir
                        pm_deal_tickets = _get_pm_partial_deals(original.symbol, ticket)

                        # Agrégation: un ou plusieurs deals
                        if len(closing_deals) > 1:
                            outcome = self._aggregate_partial_deals(original, closing_deals)
                        else:
                            outcome = self._process_closed_position(original, closing_deals[0])

                        if outcome:
                            self._outcomes.append(outcome)
                            self._save_outcome(outcome)

                            # Enregistrer dans PerformanceTracker (skip si R_UNKNOWN)
                            self._record_to_performance_tracker(outcome, original)
                            self._analyze_loss_pattern(outcome, original)

                            self._closed_tickets.add(ticket)
                            self._total_closed += 1
                            self._total_profit += outcome.profit

                            # Log
                            exit_emoji = {
                                "tp": "[TP]", "sl": "[SL]", "be": "[BE]",
                                "trailing": "[TR]", "partial": "[PA]",
                                "manual": "[MA]", "unknown": "[??]"
                            }
                            # Extraire le type de base (avant +partial)
                            base_exit = outcome.exit_type.split("+")[0]
                            emoji = exit_emoji.get(base_exit, "[??]")

                            r_str = (
                                f"R={outcome.r_multiple:.2f}"
                                if outcome.r_multiple != R_UNKNOWN
                                else "R=UNKNOWN"
                            )
                            partial_str = ""
                            if outcome.partial_deals:
                                try:
                                    n = len(json.loads(outcome.partial_deals))
                                    partial_str = f" ({n} deals)"
                                except Exception:
                                    pass

                            logger.info(
                                f"[OUTCOME] Trade cloture: #{ticket} {original.symbol} "
                                f"{emoji} {outcome.exit_type.upper()} "
                                f"P&L={outcome.profit:.2f} {r_str} "
                                f"Duree={outcome.duration_minutes:.0f}min{partial_str}"
                            )

                        # Nettoyer
                        del self._tracked_positions[ticket]

            except Exception as e:
                logger.warning(f"[OUTCOME] Erreur dans la boucle: {e}")

            # Attendre avant le prochain poll
            time.sleep(self.config.poll_interval)

        logger.info("[OUTCOME] Boucle de surveillance arretee")

    def start(self) -> None:
        """Démarre le worker de surveillance."""
        if self._running:
            logger.warning("[OUTCOME] Worker déjà en cours d'exécution")
            return

        if not MT5_AVAILABLE:
            logger.warning("[OUTCOME] MT5 non disponible - mode dégradé")

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
            f"[OUTCOME] Trade Outcome Tracker arrete - "
            f"Session: {self._total_tracked} trackes, {self._total_closed} clotures, "
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
    "R_UNKNOWN",
    "get_outcome_tracker",
    "start_outcome_tracking",
    "stop_outcome_tracking",
    "get_outcome_stats",
]
