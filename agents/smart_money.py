# agents/smart_money.py
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from agents.utils import merge_agent_params
from utils.logger import logger


@dataclass
class GapInfo:
    direction: str
    start: float
    end: float
    midpoint: float


class SmartMoneyAgent:
    """Extrait plusieurs concepts smart-money (FVG, equal highs/lows, sessions, etc.)."""

    def __init__(self, symbol: Optional[str] = None, mt5=None, profile: Optional[Dict[str, Any]] = None, **_: Any) -> None:
        self.symbol = symbol or "BTCUSD"
        self.mt5 = mt5
        self.profile = profile or {}
        defaults = {
            "timeframe": "M15",
            "lookback": 320,
            "trend_lookback": 80,
            "eq_lookback": 12,
            "eq_tolerance_pts": 6,
            "eq_tolerance_ratio": 0.0012,
            "imbalance_lookback": 40,
            "order_block_lookback": 50,
            "asian_session": {"start": "00:00", "end": "06:00"},
            "sl_mult": 1.5,
            "tp_mult": 2.2,
            "slope_threshold": 1e-4,
            "atr_period": 14,
        }
        self.params = merge_agent_params(self.symbol, "smart_money", defaults)

    # ------------------------------------------------------------------
    def _get_rates(self, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        if not self.mt5 or not hasattr(self.mt5, "get_rates"):
            return None
        try:
            data = self.mt5.get_rates(self.symbol, timeframe, count=count)
            if not data:
                return None
            df = pd.DataFrame(data)
            needed = {"time", "open", "high", "low", "close"}
            if not needed.issubset(df.columns):
                return None
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.astype({"open": float, "high": float, "low": float, "close": float})
            return df
        except Exception as exc:
            logger.warning(f"[SMART] get_rates failed for {self.symbol}: {exc}")
            return None

    @staticmethod
    def _asian_bounds(cfg: Dict[str, Any]) -> Tuple[time, time]:
        start = cfg.get("start", "00:00")
        end = cfg.get("end", "06:00")
        h_s, m_s = (int(x) for x in start.split(":"))
        h_e, m_e = (int(x) for x in end.split(":"))
        return time(hour=h_s, minute=m_s, tzinfo=timezone.utc), time(hour=h_e, minute=m_e, tzinfo=timezone.utc)

    @staticmethod
    def _linear_slope(values: pd.Series) -> float:
        if len(values) < 3:
            return 0.0
        y = values.values
        x = np.arange(len(y))
        slope, _ = np.polyfit(x, y, 1)
        base = np.mean(y) or 1.0
        return float(slope / base)

    @staticmethod
    def _find_equal_levels(series: pd.Series, tolerance: float) -> bool:
        if series.empty:
            return False
        return float(series.max() - series.min()) <= tolerance

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
        """Calcule l'ATR via EWM sur le DataFrame OHLC."""
        try:
            if df is None or len(df) < period:
                return None
            highs = df["high"].astype(float)
            lows = df["low"].astype(float)
            prev_close = df["close"].astype(float).shift(1)
            tr = pd.concat([
                (highs - lows).abs(),
                (highs - prev_close).abs(),
                (lows - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.ewm(span=period, min_periods=period).mean().iloc[-1])
            return atr if not pd.isna(atr) else None
        except Exception:
            return None

    @staticmethod
    def _detect_imbalance(df: pd.DataFrame, atr: Optional[float] = None, min_size_atr: float = 0.3) -> Optional[GapInfo]:
        window = df.tail(max(20, len(df)))
        if len(window) < 3:
            return None
        # Scan en arrière sur 15 bougies max
        scan_end = max(2, len(window) - 1)
        scan_start = max(1, scan_end - 15)
        for idx in range(scan_end, scan_start, -1):
            if idx - 1 < 0 or idx + 1 >= len(window):
                continue
            prev_candle = window.iloc[idx - 1]
            candle = window.iloc[idx]
            next_candle = window.iloc[idx + 1]
            # Bullish FVG
            if candle["low"] > prev_candle["high"] and candle["low"] > next_candle["high"]:
                start = float(prev_candle["high"])
                end = float(candle["low"])
                gap_size = abs(end - start)
                # Rejeter si FVG trop petit vs ATR
                if atr and atr > 0 and gap_size < min_size_atr * atr:
                    continue
                # Vérifier non-remplissage: si les 5 bougies suivantes descendent sous le gap
                filled = False
                future = window.iloc[idx + 1: idx + 6]
                if len(future) > 0 and float(future["low"].min()) < start:
                    filled = True
                if not filled:
                    return GapInfo("bull", start, end, (start + end) / 2.0)
            # Bearish FVG
            if candle["high"] < prev_candle["low"] and candle["high"] < next_candle["low"]:
                start = float(candle["high"])
                end = float(prev_candle["low"])
                gap_size = abs(end - start)
                if atr and atr > 0 and gap_size < min_size_atr * atr:
                    continue
                filled = False
                future = window.iloc[idx + 1: idx + 6]
                if len(future) > 0 and float(future["high"].max()) > end:
                    filled = True
                if not filled:
                    return GapInfo("bear", start, end, (start + end) / 2.0)
        return None

    @staticmethod
    def _detect_order_block(df: pd.DataFrame, bullish: bool, atr: Optional[float] = None, min_reaction: float = 1.5) -> Optional[float]:
        subset = df.tail(100)
        if len(subset) < 5:
            return None
        if bullish:
            for idx in range(len(subset) - 5, 1, -1):
                candle = subset.iloc[idx]
                if candle["close"] >= candle["open"]:
                    continue
                future = subset.iloc[idx + 1:]
                reaction = float(future["close"].max()) - float(candle["high"])
                # Exiger réaction >= 1.5x ATR
                if atr and atr > 0 and reaction < min_reaction * atr:
                    continue
                if reaction > 0:
                    ob_level = float(min(candle["open"], candle["close"], candle["low"]))
                    # Vérifier que le niveau OB n'a pas été cassé
                    if float(future["low"].min()) < ob_level:
                        continue
                    return ob_level
        else:
            for idx in range(len(subset) - 5, 1, -1):
                candle = subset.iloc[idx]
                if candle["close"] <= candle["open"]:
                    continue
                future = subset.iloc[idx + 1:]
                reaction = float(candle["low"]) - float(future["close"].min())
                if atr and atr > 0 and reaction < min_reaction * atr:
                    continue
                if reaction > 0:
                    ob_level = float(max(candle["open"], candle["close"], candle["high"]))
                    # Vérifier que le niveau OB n'a pas été cassé
                    if float(future["high"].max()) > ob_level:
                        continue
                    return ob_level
        return None

    def _detect_amd(self, df: pd.DataFrame, atr: Optional[float]) -> str:
        window = df.tail(min(len(df), 80))
        if len(window) < 10 or atr is None or atr <= 0:
            return "neutral"
        max_close = float(window["close"].max())
        min_close = float(window["close"].min())
        latest = float(window["close"].iloc[-1])
        rng = float(window["high"].max() - window["low"].min())
        if rng < atr * 1.2:
            return "accumulation"
        if abs(latest - max_close) < atr * 0.3 or abs(latest - min_close) < atr * 0.3:
            return "distribution"
        return "manipulation"

    @staticmethod
    def _compute_dynamic_multipliers(df: pd.DataFrame, direction: str) -> Tuple[float, float]:
        """Retourne (sl_mult, tp_mult) ajustés à la volatilité et la force de tendance."""
        sl_mult = 1.0
        tp_mult = 1.0
        try:
            if df is None or len(df) < 14:
                return sl_mult, tp_mult
            closes = df["close"].astype(float)
            highs = df["high"].astype(float)
            lows = df["low"].astype(float)
            avg_price = float(closes.tail(14).mean())
            if avg_price <= 0:
                return sl_mult, tp_mult
            # ATR pour ratio de volatilité
            atr_val = SmartMoneyAgent._compute_atr(df, period=14)
            if atr_val and atr_val > 0:
                vol_ratio = atr_val / avg_price
                if vol_ratio < 0.01:
                    sl_mult *= 0.8   # Réduire SL de 20% en faible volatilité
                elif vol_ratio > 0.03:
                    sl_mult *= 1.3   # Augmenter SL de 30% en forte volatilité
            # Force de tendance (mouvement directionnel / range total sur 14 bougies)
            tail = df.tail(14)
            directional_move = abs(float(tail["close"].iloc[-1]) - float(tail["close"].iloc[0]))
            total_range = float(tail["high"].max()) - float(tail["low"].min())
            if total_range > 0:
                trend_strength = directional_move / total_range
                if trend_strength > 0.6:
                    tp_mult *= 1.4   # Augmenter TP de 40% en tendance forte
                elif trend_strength < 0.3:
                    tp_mult *= 0.9   # Réduire TP de 10% en range
        except Exception:
            pass
        return sl_mult, tp_mult

    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        tf = timeframe or self.params.get("timeframe", "M15")
        lookback = int(self.params.get("lookback", 320))
        df = self._get_rates(tf, lookback)
        if df is None or df.empty:
            return {"signal": "WAIT", "reason": "no_data"}

        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        last_close = float(closes.iloc[-1])

        point = float((self.profile.get("instrument") or {}).get("point", 0.01) or 0.01)
        slope = self._linear_slope(closes.tail(int(self.params.get("trend_lookback", 80))))
        slope_th = float(self.params.get("slope_threshold", 1e-4))

        eq_len = int(self.params.get("eq_lookback", 12))
        tolerance = max(point * int(self.params.get("eq_tolerance_pts", 6)), last_close * float(self.params.get("eq_tolerance_ratio", 0.0012)))
        has_eqh = self._find_equal_levels(highs.tail(eq_len), tolerance)
        has_eql = self._find_equal_levels(lows.tail(eq_len), tolerance)

        asian_start, asian_end = self._asian_bounds(self.params.get("asian_session", {}) or {})
        now_utc = datetime.now(timezone.utc).time()
        if asian_start <= asian_end:
            in_asian = asian_start <= now_utc <= asian_end
        else:
            in_asian = now_utc >= asian_start or now_utc <= asian_end

        atr = self._compute_atr(df, period=int(self.params.get("atr_period", 14)))

        imbalance = self._detect_imbalance(df.tail(int(self.params.get("imbalance_lookback", 40))), atr=atr)

        bull_ob = self._detect_order_block(df, bullish=True, atr=atr)
        bear_ob = self._detect_order_block(df, bullish=False, atr=atr)
        amd_stage = self._detect_amd(df, atr)

        signal = "WAIT"
        rationale = []

        if slope > slope_th:
            if imbalance and imbalance.direction == "bull":
                signal = "LONG"; rationale.append("bullish_fvg")
            elif has_eql:
                signal = "LONG"; rationale.append("equal_lows")
            elif amd_stage == "distribution":
                signal = "LONG"; rationale.append("distribution_breakout")
        elif slope < -slope_th:
            if imbalance and imbalance.direction == "bear":
                signal = "SHORT"; rationale.append("bearish_fvg")
            elif has_eqh:
                signal = "SHORT"; rationale.append("equal_highs")
            elif amd_stage == "distribution":
                signal = "SHORT"; rationale.append("distribution_drop")

        if signal == "WAIT" and not in_asian:
            if has_eql and slope >= 0:
                signal = "LONG"; rationale.append("asian_liquidity_sweep")
            elif has_eqh and slope <= 0:
                signal = "SHORT"; rationale.append("asian_liquidity_sweep")

        entry = imbalance.midpoint if imbalance else last_close
        sl = None
        tp = None
        if signal in ("LONG", "SHORT"):
            dyn_sl, dyn_tp = self._compute_dynamic_multipliers(df, signal)
            sl_mult = float(self.params.get("sl_mult", 1.5)) * dyn_sl
            tp_mult = float(self.params.get("tp_mult", 2.2)) * dyn_tp
            if atr and atr > 0:
                base = atr * sl_mult
                if signal == "LONG":
                    sl = entry - base
                    tp = entry + atr * tp_mult
                    if bull_ob:
                        sl = min(sl, bull_ob)
                else:
                    sl = entry + base
                    tp = entry - atr * tp_mult
                    if bear_ob:
                        sl = max(sl, bear_ob)
            else:
                offset = point * 80
                if signal == "LONG":
                    sl = entry - offset
                    tp = entry + offset * 1.8
                else:
                    sl = entry + offset
                    tp = entry - offset * 1.8

        indicators: Dict[str, float] = {}
        indicators[f"SMART_TREND_{tf}"] = slope
        if atr:
            indicators[f"SMART_ATR_{tf}"] = atr
        if imbalance:
            indicators[f"SMART_FVG_SIZE_{tf}"] = abs(imbalance.end - imbalance.start)

        insights = {
            "trend_slope": slope,
            "equal_highs": has_eqh,
            "equal_lows": has_eql,
            "imbalance": imbalance.direction if imbalance else None,
            "asian_session": in_asian,
            "order_block_bull": bull_ob,
            "order_block_bear": bear_ob,
            "amd_stage": amd_stage,
            "rationale": rationale,
        }

        return {
            "signal": signal,
            "price": entry,
            "sl": sl,
            "tp": tp,
            "indicators": indicators,
            "insights": insights,
        }
