"""
Simplified RiskManager providing the APIs used by the orchestrator.

The original project features an extensive risk module; this trimmed version
focuses on the primitives the Whale module and orchestrator rely on:
    - daily loss guarding
    - position sizing
    - whale sizing helper (size_by_scores)
    - trailing stop helper
    - FIX 2026-02-20: global kill switch (étape 2.1)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import math
import os
import json
import logging
import threading
import pytz
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None

try:
    from utils.config import load_config, get_symbol_profile
except Exception:  # pragma: no cover
    load_config = lambda: {}

    def get_symbol_profile(sym: str) -> dict:  # type: ignore
        return {}

try:
    from utils.logger import logger
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)

try:
    from utils.whale_scoring import ScoreBundle
except Exception:  # pragma: no cover
    @dataclass
    class ScoreBundle:  # type: ignore
        trust_score: float
        signal_score: float

        @property
        def composite(self) -> float:
            return max(0.0, min(1.0, 0.5 * (self.trust_score + self.signal_score)))


# FIX 2026-02-20: Guards log file (étape 2.1)
_GUARDS_LOG_PATH = os.path.join("logs", "guards.log")
_DAILY_LOSS_STATE_PATH = os.path.join("data", "daily_loss_state.json")

# Verrou thread-safe pour accès concurrent au fichier d'état
_FILE_LOCK = threading.Lock()


def _log_guard(message: str) -> None:
    """Log guard events to logs/guards.log"""
    try:
        os.makedirs(os.path.dirname(_GUARDS_LOG_PATH), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(_GUARDS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(v)))


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return math.floor((float(value) + 1e-12) / float(step)) * float(step)


# ═══════════════════════════════════════════════════════════════════════════
# AJOUT 2026-08-12 : plafond de volume exprime en ARGENT, pas en lots.
#
# Le defaut, mesure sur 5 ordres BTCUSD entre le 05/08 et le 08/08 :
#
#   date         distance de stop   lots   risque engage   ratio / budget 250 $
#   05/08 08:06     16 912 pts      0.91      153.90 $           0.62x
#   06/08 10:30      6 585 pts      0.91       59.92 $           0.24x
#   08/08 19:30      5 686 pts      0.91       51.75 $           0.21x
#
# Les lots sont constants et le risque varie d'un facteur 3 — d'un facteur 9
# si l'on remonte au 03/08 (49 264 pts, 448,31 $, 1,79x). Cause : le
# dimensionnement demandait 7,6 lots pour consommer le budget, et le plafond
# `max_volume: 0.91` le ramenait a 0,91 sans que personne ne recalcule le
# risque resultant. Un plafond exprime en LOTS ne veut rien dire tant qu'on ne
# connait pas la distance de stop : c'est le meme lot qui vaut 51 $ ou 448 $.
#
# Le plafond pertinent est donc monetaire. `plafond_lots_par_risque` renvoie le
# nombre de lots dont la perte au stop consomme exactement le budget ; il
# s'elargit quand le stop se resserre et se resserre quand le stop s'ecarte,
# ce qui maintient le risque constant.
#
# Le garde anti-emballement reste necessaire : un stop tres serre ferait
# exploser le nombre de lots (et donc le notionnel, le slippage et la marge)
# a risque monetaire constant. Il est desormais explicite et distinct, sous
# la cle `max_volume_absolu`.
# ═══════════════════════════════════════════════════════════════════════════

def plafond_lots_par_risque(budget_usd: Optional[float],
                            points_effectifs: float,
                            valeur_point: float) -> Optional[float]:
    """
    Lots dont la perte au stop consomme exactement `budget_usd`.

    None si le budget ou la distance ne permettent pas le calcul — l'appelant
    doit alors conserver son plafond statique plutot que d'inventer un chiffre.
    """
    try:
        perte_par_lot = float(points_effectifs) * float(valeur_point)
    except (TypeError, ValueError):
        return None
    if perte_par_lot <= 0 or not budget_usd or float(budget_usd) <= 0:
        return None
    return float(budget_usd) / perte_par_lot


def plafond_volume_effectif(budget_usd: Optional[float],
                            points_effectifs: float,
                            valeur_point: float,
                            max_volume: float,
                            max_volume_absolu: float = 0.0,
                            dynamique: bool = False) -> Tuple[float, str]:
    """
    Plafond de volume a appliquer, et sa source.

    `dynamique=False` (defaut) reproduit exactement l'ancien comportement :
    le plafond statique `max_volume`. Les symboles qui n'ont pas explicitement
    demande le mode monetaire ne changent donc pas de dimensionnement.

    `dynamique=True` : plafond monetaire, borne par `max_volume_absolu`
    (a defaut `max_volume`, ce qui revient a ne rien changer — la cle absolue
    doit etre posee sciemment).
    """
    statique = float(max_volume or 0.0)
    if not dynamique:
        return statique, "max_volume"

    absolu = float(max_volume_absolu or 0.0) or statique
    par_risque = plafond_lots_par_risque(budget_usd, points_effectifs, valeur_point)
    if par_risque is None:
        return statique, "max_volume (budget indisponible)"

    if absolu > 0 and par_risque > absolu:
        return absolu, "max_volume_absolu"
    return par_risque, "budget de risque"


# ═══════════════════════════════════════════════════════════════════════════
# FIX 2026-02-20: Kill Switch Global (étape 2.1)
# Stoppe TOUT le trading quand la perte journalière cumulée dépasse le seuil.
# Inclut P&L réalisé ET flottant. Persisté dans data/daily_loss_state.json.
# Se réinitialise à 00:00 UTC chaque jour.
# ═══════════════════════════════════════════════════════════════════════════

class GlobalKillSwitch:
    """Kill switch global journalier — bloque tout trading si perte > seuil."""

    def __init__(self, limit_usd: float = 400.0, floating_limit_usd: float = 0.0):
        self.limit_usd = abs(limit_usd) if limit_usd else 400.0
        # FIX 2026-03-12 R8: Seuil séparé pour le floating (0 = désactivé, utilise 2x realized)
        self.floating_limit_usd = abs(floating_limit_usd) if floating_limit_usd else (self.limit_usd * 2.0)
        self._state = self._load_state()
        self._check_day_reset()

    def _load_state(self) -> Dict[str, Any]:
        with _FILE_LOCK:
            try:
                if os.path.exists(_DAILY_LOSS_STATE_PATH):
                    with open(_DAILY_LOSS_STATE_PATH, "r", encoding="utf-8") as f:
                        return json.load(f) or {}
            except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
                logger.warning(f"[STATE] Erreur I/O {_DAILY_LOSS_STATE_PATH}: {e}")
        return {}

    def _save_state(self) -> None:
        with _FILE_LOCK:
            try:
                os.makedirs(os.path.dirname(_DAILY_LOSS_STATE_PATH), exist_ok=True)
                tmp_path = _DAILY_LOSS_STATE_PATH + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, _DAILY_LOSS_STATE_PATH)
            except (IOError, OSError) as e:
                logger.warning(f"[STATE] Erreur I/O écriture {_DAILY_LOSS_STATE_PATH}: {e}")

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_day_reset(self) -> None:
        """Réinitialise si le jour UTC a changé."""
        today = self._today_utc()
        if self._state.get("date") != today:
            self._state = {
                "date": today,
                "realized_pnl": 0.0,
                "kill_switch_triggered": False,
                "trigger_time": None,
            }
            self._save_state()

    def update_realized_pnl(self, pnl_delta: float) -> None:
        """Met à jour le P&L réalisé cumulé du jour."""
        self._check_day_reset()
        self._state["realized_pnl"] = float(self._state.get("realized_pnl", 0.0)) + float(pnl_delta)
        self._save_state()

    def check_kill_switch(self, floating_pnl: float = 0.0) -> Tuple[bool, str]:
        """
        Vérifie si le kill switch doit être activé.
        FIX 2026-03-12 R8: Seuils séparés realized vs floating.

        Args:
            floating_pnl: P&L flottant actuel (positions ouvertes)

        Returns:
            Tuple[blocked, reason]
        """
        self._check_day_reset()

        # Si déjà déclenché aujourd'hui
        if self._state.get("kill_switch_triggered", False):
            return True, "GLOBAL_DAILY_LOSS_LIMIT (already triggered)"

        realized = float(self._state.get("realized_pnl", 0.0))
        floating = float(floating_pnl)
        total_pnl = realized + floating

        # FIX 2026-03-12 R8: Seuil 1 — realized seul (pertes confirmées)
        if realized <= -self.limit_usd:
            self._state["kill_switch_triggered"] = True
            self._state["trigger_time"] = datetime.now(timezone.utc).isoformat()
            self._state["trigger_type"] = "realized"
            self._save_state()
            msg = (f"DAILY_REALIZED_LIMIT: realized={realized:.2f} <= -${self.limit_usd:.0f}")
            logger.warning(f"[KILL_SWITCH] {msg}")
            _log_guard(f"KILL_SWITCH_TRIGGERED: {msg}")
            return True, "DAILY_REALIZED_LIMIT"

        # FIX 2026-03-12 R8: Seuil 2 — floating (laisser respirer les positions)
        if total_pnl <= -self.floating_limit_usd:
            self._state["kill_switch_triggered"] = True
            self._state["trigger_time"] = datetime.now(timezone.utc).isoformat()
            self._state["trigger_type"] = "floating"
            self._save_state()
            msg = (f"DAILY_FLOATING_LIMIT: total={total_pnl:.2f} "
                   f"(realized={realized:.2f} + floating={floating:.2f}) "
                   f"<= -${self.floating_limit_usd:.0f}")
            logger.warning(f"[KILL_SWITCH] {msg}")
            _log_guard(f"KILL_SWITCH_TRIGGERED: {msg}")
            return True, "DAILY_FLOATING_LIMIT"

        return False, ""

    def get_budget_remaining(self) -> float:
        """Retourne le budget restant avant déclenchement."""
        self._check_day_reset()
        realized = float(self._state.get("realized_pnl", 0.0))
        return max(0.0, self.limit_usd + realized)

    def is_triggered(self) -> bool:
        self._check_day_reset()
        return bool(self._state.get("kill_switch_triggered", False))


# Instance globale du kill switch
_global_kill_switch: Optional[GlobalKillSwitch] = None


def get_global_kill_switch(limit_usd: float = 400.0, floating_limit_usd: float = 0.0) -> GlobalKillSwitch:
    """Récupère ou crée l'instance globale du kill switch."""
    global _global_kill_switch
    if _global_kill_switch is None:
        _global_kill_switch = GlobalKillSwitch(limit_usd, floating_limit_usd)
    return _global_kill_switch


class RiskManager:
    def __init__(self, symbol: str, profile: Optional[Dict[str, Any]] = None, cfg: Optional[Dict[str, Any]] = None):
        self.symbol = (symbol or "").upper()
        self.cfg: Dict[str, Any] = cfg or (load_config() or {})
        self.profile: Dict[str, Any] = profile or (get_symbol_profile(self.symbol) or {})

        inst = self.profile.get("instrument") or {}
        self.point: float = float(inst.get("point", 0.01) or 0.01)
        self.min_lot: float = float(inst.get("min_lot", 0.01) or 0.01)
        self.lot_step: float = float(inst.get("lot_step", 0.01) or 0.01)
        self.contract_size: float = float(inst.get("contract_size", 1.0) or 1.0)
        self.point_value_per_lot: float = float(inst.get("pip_value", self.contract_size * self.point))
        if self.point_value_per_lot <= 0:
            self.point_value_per_lot = 1.0

        broker_costs = self.cfg.get("broker_costs") or {}
        self.spread_points: float = float(broker_costs.get("spread_points", 0.0))
        self.slippage_in: float = float(broker_costs.get("slippage_points_entry", 0.0))
        self.slippage_out: float = float(broker_costs.get("slippage_points_exit", 0.0))

        risk_cfg = self.cfg.get("risk") or {}
        # AJOUT 2026-08-12 : le plafond absolu par trade, jusqu'ici lu seulement
        # par l'orchestrateur (bloc RISK_CAP), sert desormais aussi a calculer
        # le plafond de volume. Sans lui, le dimensionnement visait 0,5 % de
        # l'equite (~498 $) et l'orchestrateur redescendait ensuite a 250 $ :
        # deux etages qui ne visaient pas la meme chose.
        try:
            self.max_risk_per_trade_usd: Optional[float] = float(
                risk_cfg.get("max_risk_per_trade_usd", 0) or 0) or None
        except (TypeError, ValueError):
            self.max_risk_per_trade_usd = None
        self.daily_loss_limit_pct: float = float(risk_cfg.get("daily_loss_limit_pct", 0.02))
        self.max_consecutive_losses: int = int(risk_cfg.get("max_consecutive_losses", 3))
        self.reset_limits_daily: bool = bool(risk_cfg.get("reset_limits_daily", True))
        self.tz = pytz.timezone(str(risk_cfg.get("timezone", "Europe/Zurich")))

        profile_risk = self.profile.get("risk") or {}
        rpt = float(profile_risk.get("risk_per_trade", risk_cfg.get("risk_per_trade_pct", 0.01)))
        self.risk_per_trade_pct = rpt / 100.0 if rpt > 1.0 else rpt
        if self.risk_per_trade_pct <= 0:
            self.risk_per_trade_pct = 0.01

        self._last_reset_day = self._day_key()
        self._risk_scale_today = 1.0

    # ------------------------------------------------------------------ utils
    def _day_key(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def _maybe_reset_day(self) -> None:
        if not self.reset_limits_daily:
            return
        day = self._day_key()
        if day != self._last_reset_day:
            self._last_reset_day = day
            self._risk_scale_today = 1.0

    # ------------------------------------------------------------------ public
    def is_daily_limit_reached(self, daily_loss_pct: float = 0.0, consec_losses: int = 0) -> bool:
        """
        Simple guard: if realised loss exceeds limit or losing streak is too large.
        """
        self._maybe_reset_day()
        if daily_loss_pct <= -abs(self.daily_loss_limit_pct):
            logger.info("[RISK] daily loss limit reached (%.2f%% <= %.2f%%)", daily_loss_pct * 100, -self.daily_loss_limit_pct * 100)
            return True
        if consec_losses >= self.max_consecutive_losses:
            logger.info("[RISK] consecutive losses guard (%s >= %s)", consec_losses, self.max_consecutive_losses)
            return True
        return False

    def get_equity(self) -> Optional[float]:
        try:
            if mt5:
                info = mt5.account_info()
                if info and hasattr(info, "equity"):
                    return float(info.equity)
        except Exception:
            pass
        try:
            return float((self.profile.get("account") or {}).get("equity_start"))
        except Exception:
            return None

    # FIX 2026-02-20: Helper pour obtenir le P&L flottant total (étape 2.1)
    def get_floating_pnl(self) -> float:
        """Retourne le P&L flottant total de toutes les positions ouvertes."""
        try:
            if mt5:
                positions = mt5.positions_get()
                if positions:
                    return sum(float(getattr(p, "profit", 0.0) or 0.0) for p in positions)
        except Exception:
            pass
        return 0.0

    def max_parallel_positions(self) -> int:
        try:
            risk_profile = self.profile.get("risk") or {}
            return int(risk_profile.get("max_parallel_positions", self.cfg.get("risk", {}).get("max_parallel_positions", 2)))
        except Exception:
            return 2

    # ------------------------------------------------------------- lot sizing
    def compute_position_size(self, equity: Optional[float], stop_distance_points: float) -> Optional[float]:
        try:
            self._maybe_reset_day()
            if equity is None:
                equity = self.get_equity()
            if equity is None:
                equity = 10_000.0

            if stop_distance_points is None or stop_distance_points <= 0:
                return None

            buffer_points = max(0.0, self.spread_points + self.slippage_in + self.slippage_out)
            effective_points = max(stop_distance_points + buffer_points, 1.0)
            risk_budget = equity * self.risk_per_trade_pct * self._risk_scale_today
            point_value = max(self.point_value_per_lot, 1e-6)

            # AJOUT 2026-08-12 : viser le budget EFFECTIF, le plus contraignant
            # des deux (pourcentage du profil, plafond absolu par trade). Sans
            # cela, cet etage visait ~498 $ et le bloc RISK_CAP de
            # l'orchestrateur redescendait a 250 $ : le plafond de volume
            # s'appliquait donc a des lots calcules pour un budget qui n'etait
            # pas celui reellement vise.
            budget_effectif = risk_budget
            if self.max_risk_per_trade_usd and self.max_risk_per_trade_usd < risk_budget:
                budget_effectif = self.max_risk_per_trade_usd

            lots = budget_effectif / (effective_points * point_value)
            lots = _round_step(lots, self.lot_step)
            lots = max(self.min_lot, lots)

            # Plafond max_volume depuis position_limits (audit fev2026)
            # 2026-08-12 : le plafond peut desormais etre monetaire (voir
            # plafond_volume_effectif). Comportement inchange pour les symboles
            # qui n'ont pas pose `max_volume_dynamique: true`.
            try:
                _pl = ((self.profile.get("orchestrator") or {})
                       .get("position_limits", {}) or {})
                max_vol = float(_pl.get("max_volume", 0) or 0)
                plafond, _source = plafond_volume_effectif(
                    budget_effectif, effective_points, point_value,
                    max_volume=max_vol,
                    max_volume_absolu=float(_pl.get("max_volume_absolu", 0) or 0),
                    dynamique=bool(_pl.get("max_volume_dynamique", False)),
                )
                if plafond > 0 and lots > plafond:
                    logger.info(
                        f"[RISK] {self.symbol}: lots {lots:.4f} plafonné à "
                        f"{plafond:.4f} (source={_source})"
                    )
                    lots = min(lots, plafond)
                    lots = _round_step(lots, self.lot_step)
                    if lots < self.min_lot:
                        logger.info(
                            f"[RISK] {self.symbol}: lots {lots:.4f} < min_lot {self.min_lot} après plafonnement → trade annulé"
                        )
                        return None
            except Exception:
                pass

            # AJOUT 2026-08-12 : refus explicite quand meme le lot minimum
            # depasse le budget de plus de 25 %. Jusqu'ici un stop tres large
            # sortait silencieusement de la fourchette par le bas du nombre de
            # lots : `max(self.min_lot, lots)` reintroduisait du risque que
            # personne ne mesurait.
            risque_final = lots * effective_points * point_value
            if budget_effectif > 0 and risque_final > 1.25 * budget_effectif:
                logger.warning(
                    "[RISK] %s: %.4f lot(s) engagent %.2f USD pour un budget de "
                    "%.2f USD (%.2fx) — au-dela de la tolerance de 25 %%, trade "
                    "refuse.", self.symbol, lots, risque_final, budget_effectif,
                    risque_final / budget_effectif)
                return None

            return lots
        except Exception as exc:
            logger.warning(f"[RISK] compute_position_size error: {exc}")
            return None

    def size_by_scores(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        atr: float,
        scores: ScoreBundle,
    ) -> Optional[Dict[str, Any]]:
        try:
            if scores is None:
                return {"reason": "missing_scores"}
            if price is None or float(price) <= 0:
                return {"reason": "invalid_price"}

            side_u = str(side or "").upper()
            if side_u not in {"LONG", "SHORT"}:
                return {"reason": "invalid_side"}

            atr_points = float(atr) / self.point if atr and atr > 0 else 80.0
            stop_multiplier = _clamp(1.1 - 0.3 * scores.signal_score, 0.6, 1.5)
            stop_distance_points = max(atr_points * stop_multiplier, self.spread_points + self.slippage_in + 5.0)

            lots = self.compute_position_size(None, stop_distance_points)
            if not lots or lots <= 0:
                return {"reason": "sizing_failed"}

            rr_target = max(1.6, 1.3 + 0.7 * scores.signal_score + 0.5 * scores.trust_score)
            stop_price = stop_distance_points * self.point
            if side_u == "LONG":
                sl = price - stop_price
                tp = price + stop_price * rr_target
            else:
                sl = price + stop_price
                tp = price - stop_price * rr_target

            return {"lots": float(lots), "sl": float(sl), "tp": float(tp), "rr": float(rr_target)}
        except Exception as exc:
            logger.warning(f"[RISK] size_by_scores error: {exc}")
            return {"reason": "exception"}

    # ------------------------------------------------------------ trailing SL
    def compute_trailing_stop(
        self,
        side: str,
        entry: float,
        current_sl: float,
        price: float,
        atr: float,
        *,
        start_rr: float = 1.5,
        atr_mult: float = 1.2,
        lock_rr: float = 0.5,
    ) -> Optional[float]:
        try:
            if atr is None or atr <= 0:
                return None
            side_u = side.upper()
            if side_u not in {"LONG", "SHORT"}:
                return None
            risk = abs(entry - current_sl)
            if risk <= 0:
                return None
            rr_now = (price - entry) / risk if side_u == "LONG" else (entry - price) / risk
            if rr_now < start_rr:
                return None
            trail_distance = max(atr * atr_mult, risk * 0.2)
            if side_u == "LONG":
                new_sl = max(current_sl, price - trail_distance, entry + lock_rr * risk)
                new_sl = min(new_sl, price - risk * 0.05)
            else:
                new_sl = min(current_sl, price + trail_distance, entry - lock_rr * risk)
                new_sl = max(new_sl, price + risk * 0.05)
            return float(new_sl)
        except Exception:
            return None
