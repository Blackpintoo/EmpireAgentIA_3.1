# agents/price_action.py
import math
import pandas as pd
from typing import Optional, Dict, Any

class PriceActionAgent:
    """
    Détecte:
      - BOS (Break Of Structure) : cassure swing high/low récente
      - FBO (False BreakOut)     : mèche au-dessus/au-dessous d’un swing mais close réintégré
      - OTE (zone 62–79% retracement) sur le dernier swing (signal plus faible)
    Retourne un dict: {"signal": "LONG|SHORT|WAIT", "price": float, "sl": float, "tp": float}
    """

    def __init__(self, symbol: str, mt5=None, profile: Optional[dict]=None, timeframe: str="M15",
                 lookback: int=300, swing_lookback: int=20, atr_period: int=14):
        self.symbol = symbol
        self.mt5 = mt5
        self.profile = profile or {}
        self.params = {
            "timeframe": timeframe,
            "lookback": lookback,
            "swing_lookback": swing_lookback,
            "atr_period": atr_period,
        }

    # -- utils --
    def _get_rates(self, tf: str, count: int):
        if not self.mt5 or not hasattr(self.mt5, "get_rates"):
            return []
        try:
            return self.mt5.get_rates(self.symbol, tf, count=count) or []
        except Exception:
            return []

    def _to_df(self, bars) -> Optional[pd.DataFrame]:
        if not bars:
            return None
        df = pd.DataFrame(bars)
        need = {"time","open","high","low","close"}
        if not need.issubset(set(df.columns)):
            return None
        return df

    def _atr(self, df: pd.DataFrame, period: int=14) -> Optional[float]:
        try:
            h,l,c = df["high"], df["low"], df["close"]
            prev_c = c.shift(1)
            tr = pd.concat([(h-l), (h-prev_c).abs(), (l-prev_c).abs()], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            return float(atr) if pd.notna(atr) else None
        except Exception:
            return None

    def _last_swing_high_low(self, df: pd.DataFrame, swing_lookback: int):
        """
        Retourne (swing_high, swing_low) récents (basés sur rolling).
        """
        try:
            rolling_high = df["high"].rolling(swing_lookback).max()
            rolling_low  = df["low"].rolling(swing_lookback).min()
            # on prend les valeurs N-2 (pour éviter la bougie courante et précédente)
            sh = float(rolling_high.iloc[-3])
            sl = float(rolling_low.iloc[-3])
            return sh, sl
        except Exception:
            return None, None

    def _detect_bos_fbo(self, df: pd.DataFrame, swing_high: float, swing_low: float) -> Dict[str, bool]:
        """
        BOS up: close > swing_high
        BOS dn: close < swing_low
        FBO up: high > swing_high et close < swing_high
        FBO dn: low < swing_low  et close > swing_low
        """
        res = {"bos_up": False, "bos_dn": False, "fbo_up": False, "fbo_dn": False}
        try:
            last = df.iloc[-1]
            high, low, close = float(last["high"]), float(last["low"]), float(last["close"])
            if swing_high is not None and swing_low is not None:
                if close > swing_high: res["bos_up"] = True
                if close < swing_low:  res["bos_dn"] = True
                if high > swing_high and close < swing_high: res["fbo_up"] = True
                if low  < swing_low  and close > swing_low:  res["fbo_dn"] = True
        except Exception:
            pass
        return res

    def _ote_zone(self, df: pd.DataFrame):
        """
        OTE (Optimal Trade Entry) : zone fib 62–79% du dernier swing impulsif (sur ~50 bougies).
        Retourne (ote_min, ote_max, direction_swing)
        """
        try:
            window = 50
            sub = df.iloc[-window:]
            hi_row = sub["high"].idxmax()
            lo_row = sub["low"].idxmin()
            hi = float(sub.loc[hi_row, "high"])
            lo = float(sub.loc[lo_row, "low"])
            if hi_row > lo_row:
                # swing down
                length = hi - lo
                ote_min = lo + 0.62 * length
                ote_max = lo + 0.79 * length
                return (ote_min, ote_max, "SHORT")
            else:
                # swing up
                length = hi - lo
                ote_max = hi - 0.62 * length
                ote_min = hi - 0.79 * length
                return (ote_min, ote_max, "LONG")
        except Exception:
            return (None, None, "")

    # -- entrée principale --
    def generate_signal(self, timeframe: Optional[str]=None) -> Dict[str, Any]:
        tf = timeframe or self.params["timeframe"]
        lb = int(self.params["lookback"])
        sw = int(self.params["swing_lookback"])
        atr_p = int(self.params["atr_period"])

        bars = self._get_rates(tf, lb)
        df = self._to_df(bars)
        if df is None or len(df) < max(atr_p+5, sw+5):
            return {"signal":"WAIT"}

        atr = self._atr(df, atr_p)
        swing_high, swing_low = self._last_swing_high_low(df, sw)
        if swing_high is None or swing_low is None or atr is None:
            return {"signal":"WAIT"}

        flags = self._detect_bos_fbo(df, swing_high, swing_low)
        last_close = float(df["close"].iloc[-1])

        # logique de décision (priorité: FBO > BOS)
        sig = ""
        sl = tp = None

        if flags["fbo_up"]:
            sig = "SHORT"
            sl = swing_high
        elif flags["fbo_dn"]:
            sig = "LONG"
            sl = swing_low
        elif flags["bos_up"]:
            sig = "LONG"
            sl = swing_low
        elif flags["bos_dn"]:
            sig = "SHORT"
            sl = swing_high
        else:
            # si pas de BOS/FBO, check OTE
            ote_min, ote_max, ote_dir = self._ote_zone(df)
            if ote_dir and ote_min and ote_max:
                if ote_dir == "LONG" and ote_min <= last_close <= ote_max:
                    sig = "LONG"; sl = swing_low
                elif ote_dir == "SHORT" and ote_min <= last_close <= ote_max:
                    sig = "SHORT"; sl = swing_high

        if not sig:
            return {"signal":"WAIT"}

        # TP via ratio ATR + RR minimal
        tp_mult = 2.5
        if sig == "LONG":
            tp = last_close + tp_mult * atr
        else:
            tp = last_close - tp_mult * atr

            # distances mini (broker)
        point = float((self.profile or {}).get("instrument", {}).get("point", 0.01) or 0.01)
        min_dist = 50 * point
        if abs(last_close - float(sl)) < min_dist:
            sl = last_close - min_dist if sig == "LONG" else last_close + min_dist
        if abs(float(tp) - last_close) < min_dist:
            tp = last_close + min_dist if sig == "LONG" else last_close - min_dist

        rr = abs(float(tp) - last_close) / max(1e-9, abs(last_close - float(sl)))
        if rr < 1.5:
            # étire TP pour RR mini
            if sig == "LONG":
                tp = last_close + 1.5 * abs(last_close - float(sl))
            else:
                tp = last_close - 1.5 * abs(last_close - float(sl))

        return {
            "signal": sig,
            "price": last_close,
            "sl": float(sl) if sl else None,
            "tp": float(tp) if tp else None,
            "debug": {"atr": atr, "rr": rr} }
