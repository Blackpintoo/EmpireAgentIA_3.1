"""
Simplified RiskManager providing the APIs used by the orchestrator.

The original project features an extensive risk module; this trimmed version
focuses on the primitives the Whale module and orchestrator rely on:
    - daily loss guarding
    - position sizing
    - whale sizing helper (size_by_scores)
    - trailing stop helper
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import math
import pytz
from datetime import datetime

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
    import logging

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


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(v)))


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return math.floor((float(value) + 1e-12) / float(step)) * float(step)


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

            lots = risk_budget / (effective_points * point_value)
            lots = _round_step(lots, self.lot_step)
            lots = max(self.min_lot, lots)
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
