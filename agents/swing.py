# agents/swing.py
from __future__ import annotations
import math, time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import pandas as pd

# MetaTrader5 (fallback natif si MT5Client non fourni)
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

# -------------------------- helpers --------------------------
def _canon_to_broker(sym: str) -> str:
    """Convertit un symbole canonique vers le symbole broker si nécessaire."""
    s = (sym or "").upper()
    # Pas de mapping nécessaire actuellement
    return s

def _tf_to_minutes(tf: str) -> int:
    return {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(str(tf).upper(), 60)

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))

def _ema(series: pd.Series, period: int) -> pd.Series:
    return pd.Series(series, dtype="float64").ewm(span=int(period), adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    s = pd.Series(series, dtype="float64")
    d = s.diff()
    up = d.where(d > 0, 0.0).rolling(period).mean()
    dn = (-d.where(d < 0, 0.0)).rolling(period).mean()
    rs = up / (dn.replace(0, 1e-12))
    out = 100 - (100 / (1 + rs))
    return out.ffill().fillna(50.0)

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = pd.to_numeric(df["high"], errors="coerce")
    l = pd.to_numeric(df["low"],  errors="coerce")
    c = pd.to_numeric(df["close"],errors="coerce")
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(int(period)).mean()

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

# -------------------------- params --------------------------
@dataclass
class SwingParams:
    timeframe: str = "H1"
    lookback: int = 400
    ema_period: int = 50
    atr_period: int = 14
    rsi_period: int = 14

    # FIX 2026-02-20: RSI 45/55 (étape 4.3)
    # Trend rules
    trend_rsi_long: float = 55.0
    trend_rsi_short: float = 45.0
    trend_sl_mult: float = 1.5
    trend_tp_mult: float = 2.4

    # Range rules
    range_rsi_long: float = 32.0
    range_rsi_short: float = 68.0
    range_sl_mult: float = 1.5
    range_tp_mult: float = 2.0

    # FIX 2026-02-20: slope 0.025, fallback désactivé (étape 4.3)
    # Regime detection
    slope_level: float = 0.025   # pente EMA minimale (abaissée pour meilleure détection)
    atr_level_val: float = 0.0   # réservé évolutions

    # Fallback doux — DÉSACTIVÉ (étape 4.3: génère trop de faux signaux)
    enable_fallback: bool = False
    fallback_sl_mult: float = 1.2
    fallback_tp_mult: float = 1.8

    # Filtres
    vol_window: int = 30
    vol_spike_ratio: float = 1.8
    session_hours: Optional[List[int]] = None  # None = pas de filtre
    confirm_timeframes: Optional[List[str]] = None

    # Hints publication
    notify_telegram: bool = False


class SwingAgent:
    """
    Agent swing multi-timeframe (H1 par défaut).
    - Détecte un régime simple (trend vs range) via la pente EMA.
    - Règles de décision RSI + positionnement vs EMA.
    - Retourne: {"signal": "LONG/SHORT/WAIT", "price", "sl", "tp", "regime", "ATR_<TF>", "ATR_H1/M30"}.
    - Compatible avec l’orchestrateur (multi-TF, hints).
    """

    def __init__(self,
                 symbol: str,
                 mt5=None, client=None, mt5_client=None,
                 profile: Optional[dict] = None, cfg: Optional[dict] = None,
                 **_):
        self.symbol = (symbol or "").upper()
        self.broker_symbol = _canon_to_broker(self.symbol)
        self.mt5 = mt5 or client or mt5_client  # MT5Client si dispo
        self.profile = profile or get_symbol_profile(self.symbol)
        self.cfg = cfg or load_config()

        # Params: config.yaml -> profile.agents.swing.params (si présents)
        base = ((self.cfg.get("swing") or {}).get("params") or {}).copy()
        try:
            prof_agents = (self.profile.get("trade_manager") or {}).get("agents", {}) or {}
            prof_swing = prof_agents.get("swing") or (self.profile.get("agents", {}) or {}).get("swing") or {}
            if isinstance(prof_swing, dict):
                # accepte { enabled:..., params:{...} } ou directement { ...params... }
                if "params" in prof_swing and isinstance(prof_swing["params"], dict):
                    base.update(prof_swing["params"])
                else:
                    base.update(prof_swing)
        except Exception:
            pass

        confirm_raw = base.get("confirm_timeframes", ["H4", "H1"])
        if isinstance(confirm_raw, str):
            confirm_tf = [seg.strip().upper() for seg in confirm_raw.split(",") if seg.strip()]
        else:
            confirm_tf = [str(tf).upper() for tf in (confirm_raw or ["H4", "H1"])]
        self.params = SwingParams(
            timeframe=str(base.get("timeframe", "H1")),
            lookback=int(base.get("lookback", 400)),
            ema_period=int(base.get("ema_period", 50)),
            atr_period=int(base.get("atr_period", 14)),
            rsi_period=int(base.get("rsi_period", 14)),
            trend_rsi_long=float(base.get("trend_rsi_long", 52.0)),
            trend_rsi_short=float(base.get("trend_rsi_short", 48.0)),
            trend_sl_mult=float(base.get("trend_sl_mult", 1.5 if "trend_sl_mult" not in base else base["trend_sl_mult"])),
            trend_tp_mult=float(base.get("trend_tp_mult", 2.4 if "trend_tp_mult" not in base else base["trend_tp_mult"])),
            range_rsi_long=float(base.get("range_rsi_long", 32.0)),
            range_rsi_short=float(base.get("range_rsi_short", 68.0)),
            range_sl_mult=float(base.get("range_sl_mult", 1.5)),
            range_tp_mult=float(base.get("range_tp_mult", 2.0)),
            slope_level=float(base.get("slope_level", 0.05)),
            atr_level_val=float(base.get("atr_level_val", 0.0)),
            enable_fallback=bool(base.get("enable_fallback", True)),
            fallback_sl_mult=float(base.get("fallback_sl_mult", 1.2)),
            fallback_tp_mult=float(base.get("fallback_tp_mult", 1.8)),
            vol_window=int(base.get("vol_window", 30)),
            vol_spike_ratio=float(base.get("vol_spike_ratio", 1.8)),
            session_hours=list(base.get("session_hours")) if base.get("session_hours") is not None else None,
            notify_telegram=bool(base.get("notify_telegram", False)),
            confirm_timeframes=confirm_tf,
        )

        # Specs instrument (point) pour distances minimales
        inst = (self.profile.get("instrument") or {}) if isinstance(self.profile, dict) else {}
        self.point = float(inst.get("point", 0.01) or 0.01)

        # Optionnel: s’assurer que le symbole est activé côté broker
        try:
            if self.mt5 and hasattr(self.mt5, "ensure_symbol"):
                self.mt5.ensure_symbol(self.broker_symbol)
        except Exception:
            pass

    # -------------------------- orchestrator wrappers --------------------------
    def run(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def get_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    def __call__(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        return self.generate_signal(timeframe=timeframe)

    # -------------------------- data helpers --------------------------
    def _get_rates(self, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        # MT5Client -> .get_rates
        try:
            if self.mt5 and hasattr(self.mt5, "get_rates"):
                bars = self.mt5.get_rates(self.broker_symbol, timeframe, count=count)
                if not bars:
                    return None
                return self._to_df(bars)
        except Exception:
            pass

        # Fallback MetaTrader5 natif
        try:
            if mt5:
                tf_map = {
                    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1
                }
                tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_H1)
                rates = mt5.copy_rates_from_pos(self.broker_symbol, tf, 0, count)
                if not rates:
                    return None
                return self._to_df(list(rates))
        except Exception:
            pass
        return None

    @staticmethod
    def _to_df(rates) -> pd.DataFrame:
        try:
            df = pd.DataFrame(rates)
        except Exception:
            return pd.DataFrame()
        if df.empty:
            return df
        req = {"time", "open", "high", "low", "close"}
        if not req.issubset(df.columns):
            return pd.DataFrame()
        try:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        except Exception:
            pass
        return df.sort_values("time").reset_index(drop=True)

    def _last_price(self) -> Optional[float]:
        # MT5Client tick
        try:
            if self.mt5 and hasattr(self.mt5, "get_tick"):
                t = self.mt5.get_tick(self.broker_symbol)
                if t:
                    if isinstance(t, dict):
                        l = t.get("last")
                        if l is None:
                            bid = t.get("bid"); ask = t.get("ask")
                            if bid is not None and ask is not None:
                                return float((bid + ask) / 2.0)
                        return float(l) if l is not None else None
                    else:
                        l = getattr(t, "last", None); b = getattr(t, "bid", None); a = getattr(t, "ask", None)
                    if l is not None:
                        return float(l)
                    if b is not None and a is not None:
                        return (float(b)+float(a))/2.0
        except Exception:
            pass
        # MetaTrader5 natif
        try:
            if mt5:
                t = mt5.symbol_info_tick(self.broker_symbol)
                if t:
                    if getattr(t, "last", None):
                        return float(t.last)
                    if getattr(t, "bid", None) and getattr(t, "ask", None):
                        return (float(t.bid) + float(t.ask)) / 2.0
        except Exception:
            pass
        return None

    # -------------------------- filters & regime --------------------------
    def _session_ok(self) -> bool:
        hours = self.params.session_hours
        if not hours:
            return True
        try:
            h = int(time.strftime("%H", time.localtime()))
            return h in set(hours)
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

    def _market_regime(self, df: pd.DataFrame) -> str:
        ema_p = int(self.params.ema_period)
        ema_v = _ema(df["close"], ema_p)
        if ema_v.isna().all():
            return "unknown"
        # pente moy (sur ~10 barres ou 5 mini)
        win = min(10, max(5, len(df) // 10))
        slope = _safe_float((ema_v.diff(win) / max(win, 1)).iloc[-1], 0.0)
        if abs(float(slope)) > float(self.params.slope_level):
            return "trend"
        return "range"
    def _wait_payload(self, tf: str, reason: str, *, regime: str = "unknown") -> Dict[str, Any]:
        return {"signal": "WAIT", "reason": reason, "agent": "swing", "timeframe": tf, "regime": regime, "score": 0.0}

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
            df_ht = self._get_rates(tf, count=max(120, self.params.atr_period + 20))
            if df_ht is None or df_ht.empty:
                continue
            ema_fast = _ema(df_ht["close"], min(len(df_ht), self.params.ema_period))
            ema_slow = _ema(df_ht["close"], min(len(df_ht), self.params.ema_period * 2))
            if ema_fast.empty or ema_slow.empty:
                continue
            bias_val = 1 if float(ema_fast.iloc[-1]) >= float(ema_slow.iloc[-1]) else -1
            score += 1 if bias_val == target else -1
            count += 1
        if count == 0:
            return 0.0
        return score / count

    def _compute_score(self, signal: str, regime: str, bias: float, rr: float) -> float:
        base = 0.0
        if signal == "LONG":
            base = 0.6 if regime == "trend" else 0.4
        elif signal == "SHORT":
            base = -0.6 if regime == "trend" else -0.4
        base += 0.3 * bias
        base += 0.1 * (rr - 1.0)
        if regime == "range":
            base += 0.05
        elif regime == "volatile":
            base -= 0.1
        return _clamp(base, -1.0, 1.0)


    # -------------------------- main signal --------------------------
    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        tf = (timeframe or self.params.timeframe or "H1").upper()

        # Fenêtre horaire (si définie)
        if not self._session_ok():
            return self._wait_payload(tf, "session")

        # Données
        lookback = int(self.params.lookback)
        df = self._get_rates(tf, count=max(lookback, 250))
        if df is None or df.empty or len(df) < max(80, self.params.ema_period + 5, self.params.atr_period + 5):
            return self._wait_payload(tf, "no_data")

        # Indicateurs
        close = pd.to_numeric(df["close"], errors="coerce")
        ema_v  = _ema(close, int(self.params.ema_period))
        rsi_v  = _rsi(close, int(self.params.rsi_period))
        atr_s  = _atr(df, int(self.params.atr_period))

        price  = _safe_float(close.iloc[-1], None)
        ema_last = _safe_float(ema_v.iloc[-1], None)
        rsi_last = _safe_float(rsi_v.iloc[-1], None)
        atr_last = _safe_float(atr_s.iloc[-1], None)

        if any(x is None for x in (price, ema_last, rsi_last, atr_last)):
            return self._wait_payload(tf, "missing_inputs")

        # Filtre de vol
        if not self._volatility_filter_ok(df):
            resp = self._wait_payload(tf, "atr_spike")
            resp[f"ATR_{tf}"] = float(atr_last) if atr_last is not None else None
            return resp

        regime = self._market_regime(df)
        signal = "WAIT"
        sl = tp = None

        # Règles
        if regime == "trend":
            if price > ema_last and rsi_last > float(self.params.trend_rsi_long):
                signal = "LONG"
                sl = price - float(self.params.trend_sl_mult) * atr_last
                tp = price + float(self.params.trend_tp_mult) * atr_last
            elif price < ema_last and rsi_last < float(self.params.trend_rsi_short):
                signal = "SHORT"
                sl = price + float(self.params.trend_sl_mult) * atr_last
                tp = price - float(self.params.trend_tp_mult) * atr_last
        else:  # range
            if rsi_last < float(self.params.range_rsi_long):
                signal = "LONG"
                sl = price - float(self.params.range_sl_mult) * atr_last
                tp = price + float(self.params.range_tp_mult) * atr_last
            elif rsi_last > float(self.params.range_rsi_short):
                signal = "SHORT"
                sl = price + float(self.params.range_sl_mult) * atr_last
                tp = price - float(self.params.range_tp_mult) * atr_last

        # Fallback doux (si rien de propre) — activable
        if signal == "WAIT" and bool(self.params.enable_fallback):
            slm = float(self.params.fallback_sl_mult)
            tpm = float(self.params.fallback_tp_mult)
            if price >= ema_last:
                signal = "LONG"
                sl = price - slm * atr_last
                tp = price + tpm * atr_last
            else:
                signal = "SHORT"
                sl = price + slm * atr_last
                tp = price - tpm * atr_last

        if signal == "WAIT" or sl is None or tp is None:
            return self._wait_payload(tf, "no_setup", regime=regime)

        # distances mini (? 50 points broker) si on a un setup
        if signal != "WAIT" and sl is not None and tp is not None:
            min_dist = max(50 * self.point, 0.0)
            if abs(price - sl) < min_dist:
                sl = price - min_dist if signal == "LONG" else price + min_dist
            if abs(tp - price) < min_dist:
                tp = price + min_dist if signal == "LONG" else price - min_dist

        rr = 0.0
        if signal != "WAIT" and price is not None and sl is not None and tp is not None:
            risk = abs(price - sl)
            reward = abs(tp - price)
            if risk > 0:
                rr = reward / risk
        bias_score = self._higher_timeframe_bias(signal)
        score = self._compute_score(signal, regime, bias_score, rr)

        # Publication ATR_<TF> + bonus ATR_H1/M30 si dispos
        out: Dict[str, Any] = {
            "signal": signal,
            "regime": regime,
            "agent": "swing",
            "timeframe": tf,
            "score": score,
            f"ATR_{tf}": float(atr_last),
        }

        try:
            for aux_tf in ("H1", "M30"):
                if aux_tf == tf:
                    continue
                aux_df = self._get_rates(aux_tf, count=max(200, self.params.atr_period + 10))
                if aux_df is not None and not aux_df.empty:
                    av = _safe_float(_atr(aux_df, self.params.atr_period).iloc[-1], None)
                    if av:
                        out[f"ATR_{aux_tf}"] = float(av)
        except Exception:
            pass

        # Hints
        if signal != "WAIT" and sl is not None and tp is not None and price is not None:
            out.update({"price": float(price), "sl": float(sl), "tp": float(tp)})

        out["bias"] = bias_score
        out["rr"] = rr
        out.update({"ema": float(ema_last), "rsi": float(rsi_last)})

        return out
