# agents/scalping.py
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import pandas as pd

# ---- Dépendances projet (fallback sûrs) -------------------------------------
try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None

try:
    from utils.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.config import get_symbol_profile
except Exception:
    def get_symbol_profile(sym: str) -> dict:  # type: ignore
        return {}

try:
    from agents.utils import merge_agent_params
except Exception:
    def merge_agent_params(symbol: str, agent_key: str, defaults):  # type: ignore
        return dict(defaults or {})

# -----------------------------------------------------------------------------
# Mémoire module : anti-spam par bougie + cooldown rapides
_LAST_BAR_DONE: Dict[str, int] = {}     # key=f"{symbol}:{tf}" -> epoch bar open
_COOLDOWN_UNTIL: Dict[str, float] = {}  # key=symbol -> unix ts
# -----------------------------------------------------------------------------


def _tf_to_minutes(tf: str) -> int:
    m = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
    return int(m.get(str(tf).upper(), 1))

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=int(period), adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / (loss.replace(0, 1e-12))
    return 100 - (100 / (1 + rs))

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=int(period)).mean()

def _now() -> float:
    return time.time()


@dataclass
class ScalpingParams:
    timeframe: str = "M1"
    session_hours: List[int] = None
    max_spread: float = 100.0
    max_trades_per_hour: int = 6  # (optionnel: non utilisé ici, l’orchestrateur garde déjà)
    # FIX 2026-02-20: RSI period 9, EMA 13, RSI 72/28 (étape 4.2)
    rsi_period: int = 9
    ema_period: int = 13
    atr_period: int = 14
    rsi_overbought: float = 72
    rsi_oversold: float = 28
    tp_mult: float = 2.0
    sl_mult: float = 1.5
    vol_window: int = 20
    vol_spike_ratio: float = 1.2
    notify_telegram: bool = True
    cooldown_seconds: int = 60
    per_bar_only: bool = True
    higher_timeframes: List[str] = None
    regime_lookback: int = 120

    def __post_init__(self):
        if self.session_hours is None:
            self.session_hours = list(range(0, 24))
        if self.higher_timeframes is None:
            self.higher_timeframes = ["M5", "M15"]


class ScalpingAgent:
    """
    Agent de scalping robuste (M1 par défaut) :
      - filtres : heures session, spread, volatilité, anti-spam par bougie, cooldown court
      - signaux RSI/EMA + confirmation micro-trend
      - SL/TP en ATR (params.sl_mult/tp_mult)
      - fournit hints: price/sl/tp
    API flexible : l’orchestrateur peut appeler .generate_signal(timeframe=...), .run(), .get_signal(), etc.
    """

    def __init__(self, symbol: str, mt5=None, profile: Optional[dict] = None, cfg: Optional[dict] = None):
        self.symbol = (symbol or "").upper()
        self.mt5 = mt5  # MT5Client de utils.mt5_client, sinon None → on essaiera MetaTrader5 direct
        self.profile = profile or get_symbol_profile(self.symbol)

        defaults = {
            "timeframe": "M1",
            "session_hours": list(range(7, 23)),
            "max_spread": 35.0,
            "max_trades_per_hour": 6,
            # FIX 2026-02-20: RSI period 9, EMA 13, RSI 72/28 (étape 4.2)
            "rsi_period": 9,
            "ema_period": 13,
            "atr_period": 14,
            "rsi_overbought": 72,
            "rsi_oversold": 28,
            "tp_mult": 2.0,
            "sl_mult": 1.6,
            "vol_window": 20,
            "vol_spike_ratio": 1.2,
            "notify_telegram": True,
            "cooldown_seconds": 90,
            "per_bar_only": True,
            "higher_timeframes": ["M5", "M15"],
            "regime_lookback": 120,
        }
        p_raw = merge_agent_params(self.symbol, "scalping", defaults)

        higher_raw = p_raw.get("higher_timeframes", defaults["higher_timeframes"])
        if isinstance(higher_raw, (list, tuple)):
            higher_tf = [str(tf).upper() for tf in higher_raw]
        elif isinstance(higher_raw, str):
            higher_tf = [seg.strip().upper() for seg in higher_raw.split(",") if seg.strip()]
        else:
            higher_tf = [str(tf).upper() for tf in defaults["higher_timeframes"]]
        regime_lb = int(p_raw.get("regime_lookback", defaults["regime_lookback"]))
        self.params = ScalpingParams(
            timeframe=str(p_raw.get("timeframe", defaults["timeframe"])),
            session_hours=list(p_raw.get("session_hours", defaults["session_hours"])),
            max_spread=float(p_raw.get("max_spread", defaults["max_spread"])),
            max_trades_per_hour=int(p_raw.get("max_trades_per_hour", defaults["max_trades_per_hour"])),
            rsi_period=int(p_raw.get("rsi_period", defaults["rsi_period"])),
            ema_period=int(p_raw.get("ema_period", defaults["ema_period"])),
            atr_period=int(p_raw.get("atr_period", defaults["atr_period"])),
            rsi_overbought=float(p_raw.get("rsi_overbought", defaults["rsi_overbought"])),
            rsi_oversold=float(p_raw.get("rsi_oversold", defaults["rsi_oversold"])),
            tp_mult=float(p_raw.get("tp_mult", defaults["tp_mult"])),
            sl_mult=float(p_raw.get("sl_mult", defaults["sl_mult"])),
            vol_window=int(p_raw.get("vol_window", defaults["vol_window"])),
            vol_spike_ratio=float(p_raw.get("vol_spike_ratio", defaults["vol_spike_ratio"])),
            notify_telegram=bool(p_raw.get("notify_telegram", defaults["notify_telegram"])),
            cooldown_seconds=int(p_raw.get("cooldown_seconds", defaults["cooldown_seconds"])),
            per_bar_only=bool(p_raw.get("per_bar_only", defaults["per_bar_only"])),
            higher_timeframes=higher_tf,
            regime_lookback=regime_lb,
        )

        # Specs instrument (pour points/SL/TP)
        inst = self.profile.get("instrument", {}) if isinstance(self.profile, dict) else {}
        self.point = float(inst.get("point", 0.01) or 0.01)

    # ----------------------------------------------------------------- helpers
    def _key(self, timeframe: str) -> str:
        return f"{self.symbol}:{timeframe}"

    def _get_rates(self, timeframe: str, count: int = 250) -> Optional[pd.DataFrame]:
        """
        Essaie d'abord via MT5Client (utils.mt5_client), puis MetaTrader5 direct si dispo.
        Retourne DataFrame avec colonnes: time, open, high, low, close.
        """
        try:
            # via MT5Client wrapper
            if self.mt5 and hasattr(self.mt5, "get_rates"):
                bars = self.mt5.get_rates(self.symbol, timeframe, count=count)
                if not bars:
                    return None
                df = pd.DataFrame(bars)
                return df
        except Exception:
            pass

        # fallback MetaTrader5 direct
        try:
            if mt5 is None:
                return None
            tf_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M1)
            rates = mt5.copy_rates_from_pos(self.symbol, tf, 0, count)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(list(rates))
            return df
        except Exception:
            return None

    def _last_tick_mid(self) -> Optional[float]:
        # MT5Client
        try:
            if self.mt5 and hasattr(self.mt5, "get_tick"):
                t = self.mt5.get_tick(self.symbol)
                if t:
                    if isinstance(t, dict):
                        b, a, l = t.get("bid"), t.get("ask"), t.get("last")
                        if l is not None:
                            return float(l)
                        if b is not None and a is not None:
                            return (float(b) + float(a)) / 2.0
                    else:
                        b = getattr(t, "bid", None)
                        a = getattr(t, "ask", None)
                        l = getattr(t, "last", None)
                        if l is not None:
                            return float(l)
                        if b is not None and a is not None:
                            return (float(b) + float(a)) / 2.0
        except Exception:
            pass

        # MetaTrader5 direct
        try:
            if mt5:
                t = mt5.symbol_info_tick(self.symbol)
                if t:
                    if getattr(t, "last", None):
                        return float(t.last)
                    if getattr(t, "bid", None) and getattr(t, "ask", None):
                        return (float(t.bid) + float(t.ask)) / 2.0
        except Exception:
            pass
        return None

    def _spread_points(self) -> Optional[float]:
        try:
            if self.mt5 and hasattr(self.mt5, "get_tick"):
                t = self.mt5.get_tick(self.symbol)
                if t:
                    if isinstance(t, dict):
                        b, a = t.get("bid"), t.get("ask")
                    else:
                        b, a = getattr(t, "bid", None), getattr(t, "ask", None)
                    if b is not None and a is not None and self.point:
                        return abs(float(a) - float(b)) / float(self.point)
        except Exception:
            pass
        try:
            if mt5:
                t = mt5.symbol_info_tick(self.symbol)
                if t and getattr(t, "bid", None) and getattr(t, "ask", None) and self.point:
                    return (float(t.ask) - float(t.bid)) / float(self.point)
        except Exception:
            pass
        return None

    def _current_bar_id(self, timeframe: str) -> Optional[int]:
        """
        Identifiant de la bougie courante (epoch du début de bougie).
        """
        try:
            df = self._get_rates(timeframe, count=1)
            if df is None or df.empty:
                return None
            return int(df["time"].iloc[-1])
        except Exception:
            return None

    # ------------------------------------------------------------ core signal
    def _session_ok(self) -> bool:
        try:
            hour = int(time.strftime("%H", time.localtime()))
            return hour in set(self.params.session_hours or [])
        except Exception:
            return True

    def _volatility_filter_ok(self, df: pd.DataFrame) -> bool:
        try:
            vwin = max(5, int(self.params.vol_window))
            atr_series = _atr(df, period=max(5, int(self.params.atr_period)))
            recent = float(atr_series.iloc[-1])
            base = float(atr_series.tail(vwin).mean())
            if base <= 0:
                return True
            ratio = recent / base
            return ratio <= float(self.params.vol_spike_ratio)
        except Exception:
            return True

    def _trend_bias(self, close: pd.Series, ema: pd.Series) -> str:
        """
        Micro-biais : 'UP', 'DOWN' ou '' selon la position du close vs EMA et la pente EMA.
        """
        try:
            slope = float(ema.iloc[-1] - ema.iloc[-3]) if len(ema) >= 3 else 0.0
            above = float(close.iloc[-1]) > float(ema.iloc[-1])
            if above and slope > 0:
                return "UP"
            if (not above) and slope < 0:
                return "DOWN"
        except Exception:
            pass
        return ""
    def _wait_response(self, tf: str, reason: str, *, regime: str = "unknown", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp: Dict[str, Any] = {
            "signal": "WAIT",
            "reason": reason,
            "agent": "scalping",
            "timeframe": tf,
            "regime": regime,
            "score": 0.0,
        }
        if extra:
            resp.update(extra)
        return resp

    def _detect_regime(self, df: pd.DataFrame) -> str:
        try:
            lookback = max(30, int(self.params.regime_lookback))
            window = df.tail(lookback)
            close = window["close"]
            ema_fast = _ema(close, min(len(close), 34))
            ema_slow = _ema(close, min(len(close), 89))
            if ema_fast.empty or ema_slow.empty:
                return "range"
            if len(ema_fast) > 5:
                slope = float(ema_fast.iloc[-1] - ema_fast.iloc[-5])
            else:
                slope = float(ema_fast.iloc[-1] - ema_fast.iloc[0])
            denom = max(abs(float(close.iloc[-1])), 1e-6)
            slope_norm = slope / denom
            if abs(slope_norm) > 0.001:
                if float(ema_fast.iloc[-1]) >= float(ema_slow.iloc[-1]):
                    return "trend_up"
                return "trend_down"
            vol = close.pct_change().rolling(max(10, lookback // 2)).std().iloc[-1]
            if vol and abs(float(vol)) > 0.015:
                return "volatile"
        except Exception:
            return "unknown"
        return "range"

    def _higher_timeframe_bias(self, signal: str, regime: str) -> float:
        target = {"LONG": 1, "SHORT": -1}.get(signal, 0)
        if target == 0:
            return 0.0
        frames = [str(tf).upper() for tf in (self.params.higher_timeframes or [])]
        score = 0.0
        count = 0
        for tf in frames:
            if tf == self.params.timeframe.upper():
                continue
            df_ht = self._get_rates(tf, count=200)
            if df_ht is None or df_ht.empty:
                continue
            ema_fast = _ema(df_ht["close"], 34)
            ema_slow = _ema(df_ht["close"], 89)
            if ema_fast.empty or ema_slow.empty:
                continue
            bias_val = 1 if float(ema_fast.iloc[-1]) >= float(ema_slow.iloc[-1]) else -1
            score += 1 if bias_val == target else -1
            count += 1
        if count == 0:
            return 0.0
        return score / count

    def _compute_score(self, signal: str, regime: str, bias: float) -> float:
        base = 0.0
        if signal == "LONG":
            base = 0.6
        elif signal == "SHORT":
            base = -0.6
        base += 0.3 * bias
        if regime.startswith("trend"):
            if regime.endswith("up"):
                base += 0.2 if signal == "LONG" else -0.2
            elif regime.endswith("down"):
                base += 0.2 if signal == "SHORT" else -0.2
        elif regime == "range":
            base += 0.1
        elif regime == "volatile":
            base -= 0.1
        return _clamp(base, -1.0, 1.0)


    # Méthode principale appelée par l’orchestrateur
    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        tf = (timeframe or self.params.timeframe or "M1").upper()
        regime = "unknown"

        if not self._session_ok():
            return self._wait_response(tf, "session")

        key = self._key(tf)
        now = _now()
        if now < _COOLDOWN_UNTIL.get(self.symbol, 0.0):
            return self._wait_response(tf, "cooldown")

        if self.params.per_bar_only:
            cur_bar = self._current_bar_id(tf)
            if cur_bar is not None and _LAST_BAR_DONE.get(key) == cur_bar:
                return self._wait_response(tf, "per_bar_only")

        spr = self._spread_points()
        if spr is not None and spr > float(self.params.max_spread):
            return self._wait_response(tf, f"spread>{spr:.1f}")

        df = self._get_rates(tf, count=max(250, self.params.regime_lookback + 20))
        if df is None or df.empty or len(df) < max(50, self.params.ema_period + 5, self.params.atr_period + 5):
            return self._wait_response(tf, "no_data")

        close = df["close"]
        ema = _ema(close, self.params.ema_period)
        rsi = _rsi(close, self.params.rsi_period)
        atr = _atr(df, self.params.atr_period)

        if not self._volatility_filter_ok(df):
            resp = self._wait_response(tf, "atr_spike")
            try:
                resp[f"ATR_{tf}"] = float(atr.iloc[-1])
            except Exception:
                pass
            return resp

        price = float(close.iloc[-1])
        ema_v = float(ema.iloc[-1])
        rsi_v = float(rsi.iloc[-1])
        atr_raw = atr.iloc[-1]
        atr_v = float(atr_raw) if not math.isnan(float(atr_raw)) else None

        regime = self._detect_regime(df)
        bias = self._trend_bias(close, ema)

        signal = "WAIT"
        if rsi_v <= float(self.params.rsi_oversold) and price >= ema_v and bias == "UP":
            signal = "LONG"
        elif rsi_v >= float(self.params.rsi_overbought) and price <= ema_v and bias == "DOWN":
            signal = "SHORT"
        else:
            if bias == "UP" and price > ema_v and rsi_v < 60:
                signal = "LONG"
            elif bias == "DOWN" and price < ema_v and rsi_v > 40:
                signal = "SHORT"

        if signal == "WAIT":
            return self._wait_response(tf, "no_setup", regime=regime)

        if atr_v is None or atr_v <= 0:
            return self._wait_response(tf, "no_atr", regime=regime)

        if signal == "LONG":
            sl = price - float(self.params.sl_mult) * atr_v
            tp = price + float(self.params.tp_mult) * atr_v
        else:
            sl = price + float(self.params.sl_mult) * atr_v
            tp = price - float(self.params.tp_mult) * atr_v

        min_dist = max(50 * self.point, 0.0)
        if abs(price - sl) < min_dist:
            sl = price - min_dist if signal == "LONG" else price + min_dist
        if abs(tp - price) < min_dist:
            tp = price + min_dist if signal == "LONG" else price - min_dist

        try:
            cur_bar = self._current_bar_id(tf)
            if cur_bar is not None:
                _LAST_BAR_DONE[key] = cur_bar
            _COOLDOWN_UNTIL[self.symbol] = _now() + int(self.params.cooldown_seconds)
        except Exception:
            pass

        ht_bias = self._higher_timeframe_bias(signal, regime)
        score = self._compute_score(signal, regime, ht_bias)

        result = {
            "signal": signal,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "timeframe": tf,
            "agent": "scalping",
            "regime": regime,
            "score": score,
            "debug": {"rsi": float(rsi_v), "ema": float(ema_v), "atr": float(atr_v), "spread": spr, "ht_bias": ht_bias}
        }
        return result
    # Aliases pour compatibilité avec l’orchestrateur
    def run(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def get_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def __call__(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)
