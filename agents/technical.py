# agents/technical.py
from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import pandas as pd

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None

# logger
try:
    from utils.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

# config
try:
    from utils.config import load_config, get_symbol_profile
except Exception:
    load_config = lambda: {}
    def get_symbol_profile(sym: str) -> dict:  # type: ignore
        return {}

# --------------------------------- helpers ---------------------------------
def _tf_to_minutes(tf: str) -> int:
    return {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(str(tf).upper(), 1)

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

def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = _ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        v = float(x)
        if pd.isna(v):
            return default
        return v
    except Exception:
        return default

def _canon_to_broker(sym: str) -> str:
    """Convertit un symbole canonique vers le symbole broker si nécessaire."""
    s = (sym or "").upper()
    # Pas de mapping nécessaire actuellement
    return s

# --------------------------------- params ----------------------------------
@dataclass
class TechnicalParams:
    timeframe: str = "M30"
    session_hours: Optional[List[int]] = None
    confirm_timeframes: Optional[List[str]] = None
    regime_lookback: int = 180
    ema_period: int = 50
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    tp_mult: float = 2.5
    sl_mult: float = 2.0
    rsi_overbought: float = 60
    rsi_oversold: float = 40
    macd_eps: float = 0.0008
    # filtres
    vol_window: int = 20
    vol_spike_ratio: float = 1.8
    # notifs éventuelles
    notify_telegram: bool = True

    def __post_init__(self) -> None:
        if self.session_hours is None:
            self.session_hours = list(range(0, 24))
        if self.confirm_timeframes is None:
            self.confirm_timeframes = ["H4", "H1"]


class TechnicalAgent:
    """
    Agent technique multi-timeframe.
    – Renvoie un dict avec au minimum {"signal": "LONG/SHORT/WAIT"}.
    – Peut fournir des hints: "price", "sl", "tp".
    – Publie aussi des ATR utiles: "ATR_<TF>", "ATR_H1", "ATR_M30".
    """

    def __init__(self, symbol: str, mt5=None, profile: Optional[dict] = None, cfg: Optional[dict] = None):
        self.symbol = (symbol or "").upper()
        self.broker_symbol = _canon_to_broker(self.symbol)
        self.mt5 = mt5  # MT5Client (si dispo)
        self.profile = profile or get_symbol_profile(self.symbol)
        self.cfg = cfg or load_config()

        # --- instrument (pour distances mini) ---
        inst = (self.profile or {}).get("instrument", {})
        self.point = float(inst.get("point", 0.01) or 0.01)

        # --- params depuis config.yaml puis override profil ---
        defaults = {
            "timeframe": "M30",
            "session_hours": list(range(7, 23)),
            "confirm_timeframes": ["H4", "H1"],
            "regime_lookback": 180,
            "ema_period": 50,
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "atr_period": 14,
            "tp_mult": 2.5,
            "sl_mult": 2.0,
            "rsi_overbought": 60,
            "rsi_oversold": 40,
            "macd_eps": 0.0008,
            "vol_window": 20,
            "vol_spike_ratio": 1.8,
            "notify_telegram": True,
        }
        p_raw = dict(defaults)
        p_raw.update((self.cfg.get("technical") or {}).get("params") or {})
        prof_agents = (self.profile.get("trade_manager", {}) or {}).get("agents", {})
        p_prof1 = ((self.profile.get("trade_manager") or {}).get("agents", {}) or {}).get("technical", {})
        p_prof2 = (self.profile.get("orchestrator") or {}).get("agents", {})
        if isinstance(p_prof1, dict) and "enabled" in p_prof1:
            p_raw.update(p_prof1.get("params") or {})
        elif isinstance(p_prof1, dict):
            p_raw.update(p_prof1 or {})
        if isinstance(p_prof2, dict):
            tech_cfg = p_prof2.get("technical")
            if isinstance(tech_cfg, dict):
                p_raw.update(tech_cfg.get("params", {}))

        confirm_raw = p_raw.get("confirm_timeframes", defaults["confirm_timeframes"])
        if isinstance(confirm_raw, str):
            confirm_tf = [seg.strip().upper() for seg in confirm_raw.split(",") if seg.strip()]
        else:
            confirm_tf = [str(tf).upper() for tf in (confirm_raw or defaults["confirm_timeframes"])]

        session_raw = p_raw.get("session_hours", defaults["session_hours"])
        if isinstance(session_raw, str):
            session_hours = [int(seg) for seg in session_raw.split(",") if seg.strip().isdigit()]
        else:
            session_hours = list(session_raw or defaults["session_hours"])

        self.params = TechnicalParams(
            timeframe=str(p_raw.get("timeframe", defaults["timeframe"])),
            session_hours=session_hours,
            confirm_timeframes=confirm_tf,
            regime_lookback=int(p_raw.get("regime_lookback", defaults["regime_lookback"])),
            ema_period=int(p_raw.get("ema_period", defaults["ema_period"])),
            rsi_period=int(p_raw.get("rsi_period", defaults["rsi_period"])),
            macd_fast=int(p_raw.get("macd_fast", defaults["macd_fast"])),
            macd_slow=int(p_raw.get("macd_slow", defaults["macd_slow"])),
            macd_signal=int(p_raw.get("macd_signal", defaults["macd_signal"])),
            atr_period=int(p_raw.get("atr_period", defaults["atr_period"])),
            tp_mult=float(p_raw.get("tp_mult", defaults["tp_mult"])),
            sl_mult=float(p_raw.get("sl_mult", defaults["sl_mult"])),
            rsi_overbought=float(p_raw.get("rsi_overbought", defaults["rsi_overbought"])),
            rsi_oversold=float(p_raw.get("rsi_oversold", defaults["rsi_oversold"])),
            macd_eps=float(p_raw.get("macd_eps", defaults["macd_eps"])),
            vol_window=int(p_raw.get("vol_window", defaults["vol_window"])),
            vol_spike_ratio=float(p_raw.get("vol_spike_ratio", defaults["vol_spike_ratio"])),
            notify_telegram=bool(p_raw.get("notify_telegram", defaults["notify_telegram"])),
        )

    # ------------------------------- market IO -------------------------------
    def _get_rates(self, timeframe: str, count: int = 300) -> Optional[pd.DataFrame]:
        """
        Récupère les données OHLC pour le timeframe spécifié.

        AUDIT 2025-12-27: Ajout de la détection et gestion des gaps de données.
        """
        df = None

        try:
            if self.mt5 and hasattr(self.mt5, "get_rates"):
                bars = self.mt5.get_rates(self.broker_symbol, timeframe, count=count)
                if bars:
                    df = pd.DataFrame(bars)
        except Exception:
            pass

        # Fallback natif MetaTrader5
        if df is None:
            try:
                if mt5:
                    tf_map = {
                        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1
                    }
                    tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
                    rates = mt5.copy_rates_from_pos(self.broker_symbol, tf, 0, count)
                    if rates:
                        df = pd.DataFrame(list(rates))
            except Exception:
                pass

        if df is None or df.empty:
            return None

        # AUDIT 2025-12-27: Détection des gaps de données
        df = self._check_and_handle_gaps(df, timeframe)

        return df

    def _check_and_handle_gaps(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        Détecte les gaps dans les données et marque les données comme invalides si nécessaire.

        AUDIT 2025-12-27 - CORRECTION #5: Gestion des gaps de données

        Un gap est détecté si la différence de timestamp entre deux barres consécutives
        est supérieure à 2x l'intervalle attendu pour le timeframe.
        """
        if df is None or df.empty or len(df) < 2:
            return df

        try:
            # Mapping des minutes par timeframe
            tf_minutes = _tf_to_minutes(timeframe)
            max_gap_seconds = tf_minutes * 60 * 2  # 2x l'intervalle attendu

            # Vérifier s'il y a une colonne time
            if 'time' not in df.columns:
                return df

            # Calculer les différences de temps
            times = pd.to_datetime(df['time'], unit='s')
            time_diffs = times.diff().dt.total_seconds()

            # Détecter les gaps
            gaps = time_diffs > max_gap_seconds
            gap_count = gaps.sum()

            if gap_count > 0:
                # Marquer les données avec un flag
                df['_has_gap'] = False
                df.loc[gaps, '_has_gap'] = True

                # Logger un warning si gaps significatifs
                if gap_count > len(df) * 0.1:  # Plus de 10% de gaps
                    logger.warning(
                        f"[DATA_QUALITY] {self.broker_symbol} {timeframe}: "
                        f"{gap_count} gaps détectés ({gap_count/len(df)*100:.1f}%) - "
                        f"signaux potentiellement affectés"
                    )
                else:
                    logger.debug(
                        f"[DATA_QUALITY] {self.broker_symbol} {timeframe}: "
                        f"{gap_count} gaps mineurs détectés"
                    )

            return df

        except Exception as e:
            logger.debug(f"[DATA_QUALITY] Erreur détection gaps: {e}")
            return df

    def _has_significant_gaps(self, df: pd.DataFrame) -> bool:
        """
        Vérifie si le DataFrame contient des gaps significatifs.

        Returns:
            True si plus de 10% des données contiennent des gaps
        """
        if df is None or df.empty:
            return True

        if '_has_gap' not in df.columns:
            return False

        gap_ratio = df['_has_gap'].sum() / len(df)
        return gap_ratio > 0.1



    # ------------------------------- filters --------------------------------
    def _volatility_filter_ok(self, df: pd.DataFrame) -> bool:
        """
        Avoid extreme volatility spikes by comparing the current ATR to its rolling baseline.
        """
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

    # ------------------------------- helpers --------------------------------
    def _session_ok(self) -> bool:
        try:
            hour = int(time.strftime("%H", time.localtime()))
            return hour in set(self.params.session_hours or [])
        except Exception:
            return True

    def _wait_payload(self, tf: str, reason: str, *, regime: str = "unknown", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "signal": "WAIT",
            "reason": reason,
            "agent": "technical",
            "timeframe": tf,
            "regime": regime,
            "score": 0.0,
        }
        if extra:
            payload.update(extra)
        return payload

    def _detect_regime(self, df: pd.DataFrame) -> str:
        try:
            lookback = max(60, int(self.params.regime_lookback))
            window = df.tail(lookback)
            close = window["close"]
            ema_fast = _ema(close, min(len(close), self.params.ema_period))
            ema_slow = _ema(close, min(len(close), self.params.ema_period * 2))
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
            vol = close.pct_change().rolling(max(10, lookback // 3)).std().iloc[-1]
            if vol and abs(float(vol)) > 0.02:
                return "volatile"
        except Exception:
            return "unknown"
        return "range"

    def _higher_timeframe_bias(self, signal: str) -> float:
        target = {"LONG": 1, "SHORT": -1}.get(signal, 0)
        if target == 0:
            return 0.0
        frames = [str(tf).upper() for tf in (self.params.confirm_timeframes or [])]
        score = 0.0
        count = 0
        for tf in frames:
            if tf == self.params.timeframe.upper():
                continue
            df_ht = self._get_rates(tf, count=200)
            if df_ht is None or df_ht.empty:
                continue
            ema_fast = _ema(df_ht["close"], min(len(df_ht), self.params.ema_period))
            ema_slow = _ema(df_ht["close"], min(len(df_ht), self.params.ema_period * 2))
            if ema_fast.empty or ema_slow.empty:
                continue
            bias = 1 if float(ema_fast.iloc[-1]) >= float(ema_slow.iloc[-1]) else -1
            score += 1 if bias == target else -1
            count += 1
        if count == 0:
            return 0.0
        return score / count

    def _compute_score(self, signal: str, regime: str, bias: float, rr: float, macd_strength: float) -> float:
        base = 0.0
        if signal == "LONG":
            base = 0.6 if regime.startswith("trend") else 0.4
        elif signal == "SHORT":
            base = -0.6 if regime.startswith("trend") else -0.4
        base += 0.25 * bias
        base += 0.1 * (rr - 1.0)
        base += 0.15 * _clamp(macd_strength, -1.0, 1.0)
        if regime == "volatile":
            base -= 0.1
        elif regime == "range":
            base += 0.05
        return _clamp(base, -1.0, 1.0)

    # ------------------------------- signal ---------------------------------
    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        tf = (timeframe or self.params.timeframe or "M30").upper()
        regime = "unknown"

        if not self._session_ok():
            return self._wait_payload(tf, "session")

        df = self._get_rates(tf, count=max(300, self.params.regime_lookback + 40))
        if df is None or df.empty or len(df) < max(80, self.params.ema_period + 10, self.params.atr_period + 10):
            return self._wait_payload(tf, "no_data")

        close = df["close"]
        ema = _ema(close, int(self.params.ema_period))
        rsi = _rsi(close, int(self.params.rsi_period))
        macd_line, macd_signal, macd_hist = _macd(close, self.params.macd_fast, self.params.macd_slow, self.params.macd_signal)
        atr_series = _atr(df, self.params.atr_period)

        if not self._volatility_filter_ok(df):
            resp = self._wait_payload(tf, "atr_spike")
            resp[f"ATR_{tf}"] = float(_safe_float(atr_series.iloc[-1], 0.0) or 0.0)
            return resp

        price = _safe_float(close.iloc[-1], None)
        ema_last = _safe_float(ema.iloc[-1], None)
        rsi_last = _safe_float(rsi.iloc[-1], None)
        macd_last = _safe_float(macd_line.iloc[-1], None)
        macd_sig_last = _safe_float(macd_signal.iloc[-1], None)
        macd_hist_last = _safe_float(macd_hist.iloc[-1], 0.0)
        atr_last = _safe_float(atr_series.iloc[-1], None)

        if any(x is None for x in (price, ema_last, rsi_last, macd_last, macd_sig_last, atr_last)):
            return self._wait_payload(tf, "missing_inputs")

        regime = self._detect_regime(df)
        ema_slope = 0.0
        try:
            ema_slope = float(ema.iloc[-1] - ema.iloc[-4]) if len(ema) >= 4 else 0.0
        except Exception:
            ema_slope = 0.0

        macd_diff = float(macd_last - macd_sig_last)
        signal = "WAIT"
        eps = float(self.params.macd_eps)
        if price > ema_last and ema_slope > 0 and macd_diff > eps and rsi_last < float(self.params.rsi_overbought):
            signal = "LONG"
        elif price < ema_last and ema_slope < 0 and macd_diff < -eps and rsi_last > float(self.params.rsi_oversold):
            signal = "SHORT"

        if signal == "WAIT":
            return self._wait_payload(tf, "no_setup", regime=regime, extra={f"ATR_{tf}": float(atr_last or 0.0)})

        if atr_last is None or atr_last <= 0:
            return self._wait_payload(tf, "no_atr", regime=regime)

        price_f = float(price)
        sl = price_f - self.params.sl_mult * atr_last if signal == "LONG" else price_f + self.params.sl_mult * atr_last
        tp = price_f + self.params.tp_mult * atr_last if signal == "LONG" else price_f - self.params.tp_mult * atr_last

        min_dist = max(50 * self.point, 0.0)
        if abs(price_f - sl) < min_dist:
            sl = price_f - min_dist if signal == "LONG" else price_f + min_dist
        if abs(tp - price_f) < min_dist:
            tp = price_f + min_dist if signal == "LONG" else price_f - min_dist

        risk = abs(price_f - sl)
        rr = abs(tp - price_f) / risk if risk > 0 else 0.0
        bias_score = self._higher_timeframe_bias(signal)
        score = self._compute_score(signal, regime, bias_score, rr, macd_diff)

        out: Dict[str, Any] = {
            "signal": signal,
            "price": price_f,
            "sl": float(sl),
            "tp": float(tp),
            "timeframe": tf,
            "agent": "technical",
            "regime": regime,
            "score": score,
            f"ATR_{tf}": float(atr_last),
            "bias": bias_score,
            "rr": rr,
            "macd": float(macd_last),
            "macd_signal": float(macd_sig_last),
            "macd_hist": float(macd_hist_last or 0.0),
            "ema": float(ema_last),
            "ema_slope": float(ema_slope),
            "rsi": float(rsi_last),
        }

        try:
            for aux_tf in ("H1", "M30"):
                if aux_tf == tf:
                    continue
                aux_df = self._get_rates(aux_tf, count=200)
                if aux_df is None or aux_df.empty:
                    continue
                atr_aux = _safe_float(_atr(aux_df, self.params.atr_period).iloc[-1], None)
                if atr_aux:
                    out[f"ATR_{aux_tf}"] = float(atr_aux)
        except Exception:
            pass

        return out



    # aliases compatibles avec l’orchestrateur
    def run(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def get_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def __call__(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)
