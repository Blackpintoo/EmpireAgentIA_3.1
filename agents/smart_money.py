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
    def _detect_imbalance(df: pd.DataFrame) -> Optional[GapInfo]:
        window = df.tail(max(3, len(df)))
        for idx in range(len(window) - 3, len(window) - 1):
            prev_candle = window.iloc[idx - 1]
            candle = window.iloc[idx]
            next_candle = window.iloc[idx + 1]
            if candle["low"] > prev_candle["high"] and candle["low"] > next_candle["high"]:
                start = float(prev_candle["high"])
                end = float(candle["low"])
                return GapInfo("bull", start, end, (start + end) / 2.0)
            if candle["high"] < prev_candle["low"] and candle["high"] < next_candle["low"]:
                start = float(candle["high"])
                end = float(prev_candle["low"])
                return GapInfo("bear", start, end, (start + end) / 2.0)
        return None

    @staticmethod
    def _detect_order_block(df: pd.DataFrame, bullish: bool) -> Optional[float]:
        subset = df.tail(60)
        if len(subset) < 5:
            return None
        if bullish:
            for idx in range(len(subset) - 5, 1, -1):
                candle = subset.iloc[idx]
                if candle["close"] >= candle["open"]:
                    continue
                future = subset.iloc[idx + 1:]
                if future["close"].max() > candle["high"]:
                    return float(min(candle["open"], candle["close"], candle["low"]))
        else:
            for idx in range(len(subset) - 5, 1, -1):
                candle = subset.iloc[idx]
                if candle["close"] <= candle["open"]:
                    continue
                future = subset.iloc[idx + 1:]
                if future["close"].min() < candle["low"]:
                    return float(max(candle["open"], candle["close"], candle["high"]))
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

        imbalance = self._detect_imbalance(df.tail(int(self.params.get("imbalance_lookback", 40))))

        asian_start, asian_end = self._asian_bounds(self.params.get("asian_session", {}) or {})
        now_utc = datetime.now(timezone.utc).time()
        if asian_start <= asian_end:
            in_asian = asian_start <= now_utc <= asian_end
        else:
            in_asian = now_utc >= asian_start or now_utc <= asian_end

        atr_period = int(self.params.get("atr_period", 14))
        prev_close = closes.shift(1)
        tr = pd.concat([(highs - lows).abs(), (highs - prev_close).abs(), (lows - prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(span=atr_period, min_periods=atr_period).mean().iloc[-1]) if len(tr) >= atr_period else None

        bull_ob = self._detect_order_block(df, bullish=True)
        bear_ob = self._detect_order_block(df, bullish=False)
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
            sl_mult = float(self.params.get("sl_mult", 1.5))
            tp_mult = float(self.params.get("tp_mult", 2.2))
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
