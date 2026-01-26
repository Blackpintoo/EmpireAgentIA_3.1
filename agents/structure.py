# agents/structure.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import math
import pandas as pd
import numpy as np

from utils.smc_patterns import (
    PatternEvent,
    compute_equilibrium,
    compute_ote_zone as smc_compute_ote_zone,
    compute_invalidation_sl,
    detect_bos,
    detect_breaker_blocks,
    detect_choch,
    detect_equal_highs,
    detect_equal_lows,
    detect_fvg,
    detect_inducement,
    detect_liquidity_sweep,
    detect_mitigation_block,
    detect_order_blocks,
    find_pivots,
)

TF_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


def _sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=max(2, n // 2)).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR (SMA) classique."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return _sma(tr, period)


def _pivot_flags(df: pd.DataFrame, w: int) -> Tuple[pd.Series, pd.Series]:
    """
    Balises swing High/Low (pivot) via max/min centrés sur fenêtre 2w+1.
    Renvoie (is_pivot_high, is_pivot_low).
    """
    if w < 1:
        w = 1
    win = 2 * w + 1
    roll_max = df["high"].rolling(win, center=True).max()
    roll_min = df["low"].rolling(win, center=True).min()
    is_ph = (df["high"] == roll_max)
    is_pl = (df["low"] == roll_min)
    # élimine les bords où la fenêtre est incomplète
    is_ph.iloc[:w] = False
    is_ph.iloc[-w:] = False
    is_pl.iloc[:w] = False
    is_pl.iloc[-w:] = False
    return is_ph.fillna(False), is_pl.fillna(False)


def _last_n(seq: List[Any], n: int) -> List[Any]:
    return seq[-n:] if len(seq) >= n else seq


def _trend_bias(
    highs: List[float], lows: List[float]
) -> Optional[str]:
    """
    Biais “structurel” simple :
      - up si HH et HL (derniers deux extrêmes)
      - down si LH et LL
      - None sinon
    """
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = highs[-1], highs[-2]   # h1 = le plus récent
    l1, l2 = lows[-1], lows[-2]
    if h1 > h2 and l1 > l2:
        return "up"
    if h1 < h2 and l1 < l2:
        return "down"
    return None


def _ote_zone(long: bool, swing_low: float, swing_high: float) -> Tuple[float, float, float]:
    """
    Zone OTE (Optimal Trade Entry) : 62%–79%.
    Renvoie (z_low, z_high, mid).
    """
    if long:
        length = swing_high - swing_low
        z_low = swing_low + 0.62 * length
        z_high = swing_low + 0.79 * length
    else:
        length = swing_high - swing_low
        z_low = swing_high - 0.79 * length
        z_high = swing_high - 0.62 * length
    return (float(min(z_low, z_high)), float(max(z_low, z_high)), float((z_low + z_high) / 2.0))


class StructureAgent:
    """
    Agent Price Action (structure) :
      - Détecte BOS (Break of Structure) et CHoCH
      - Filtre FBO (False Breakout) sur quelques barres
      - Suggère une entrée OTE + SL/TP via ATR
    Sortie : dict(signal=LONG/SHORT/WAIT, price=?, sl=?, tp=?, debug=?)
    """

    def __init__(self, symbol: Optional[str] = None, mt5=None, profile: Optional[Dict[str, Any]] = None, **kwargs):
        self.symbol = symbol
        self.mt5 = mt5
        self.profile = profile or {}
        # l’orchestrateur placera aussi self.params.timeframe si besoin
        self.params: Dict[str, Any] = (self.profile.get("agents", {}).get("structure", {}) if self.profile else {})
        # fallback si l’agent est appelé “price_action” dans d’anciens profils
        if not self.params and self.profile:
            self.params = self.profile.get("agents", {}).get("price_action", {}) or {}

    # --------------- CFG ---------------
    def _cfg(self) -> Dict[str, Any]:
        p = self.params or {}
        swing_win = int(p.get("swing_window", p.get("wing_lookback", 20)) or 20)
        smc_pivot_win = int(p.get("smc_pivot_window", max(2, swing_win // 2)))
        return {
            "lookback": int(p.get("lookback", 300)),
            "swing_window": swing_win,
            "retest_bars": int(p.get("retest_bars", 3)),
            "atr_period": int(p.get("atr_period", 14)),
            "sl_mult": float(p.get("sl_mult", 1.5)),
            "tp_mult": float(p.get("tp_mult", 2.5)),
            "smc_enabled": bool(p.get("smc_enabled", True)),
            "smc_pivot_window": smc_pivot_win,
            "smc_fvg_tol": float(p.get("smc_fvg_tolerance", 0.0)),
            "smc_eq_tolerance": float(p.get("smc_eq_tolerance", 0.001)),
        }

    # --------------- Data ---------------
    def _get_rates(self, timeframe: str, count: int) -> Optional[pd.DataFrame]:
        """
        Utilise l'interface MT5Client du projet (mt5.get_rates(symbol, timeframe, count)).
        Doit renvoyer un DataFrame avec colonnes time, open, high, low, close.
        """
        if not self.mt5 or not hasattr(self.mt5, "get_rates"):
            return None
        try:
            data = self.mt5.get_rates(self.symbol, timeframe, count=count)
            if not data:
                return None
            df = pd.DataFrame(data)
            needed = {"time", "open", "high", "low", "close"}
            if not needed.issubset(df.columns):
                # certains wrappers renvoient des namedtuples
                cols_ok = [c for c in ["time", "open", "high", "low", "close"] if hasattr(data[0], c)]
                if len(cols_ok) == 5:
                    df = pd.DataFrame([{c: getattr(x, c) for c in cols_ok} for x in data])
                else:
                    return None
            df = df.sort_index() if df.index.is_monotonic_increasing else df.sort_index()
            return df
        except Exception:
            return None

    # --------------- SMC helpers ---------------
    def _serialize_events(self, events: Dict[str, List[PatternEvent]]) -> Dict[str, List[Dict[str, Any]]]:
        serialized: Dict[str, List[Dict[str, Any]]] = {}
        for name, evts in (events or {}).items():
            serialized[name] = [
                {
                    "pattern": evt.pattern,
                    "direction": evt.direction,
                    "level": evt.level,
                    "start_idx": evt.start_idx,
                    "end_idx": evt.end_idx,
                    "meta": evt.meta,
                }
                for evt in evts
            ]
        return serialized

    def _smc_snapshot(
        self,
        df: pd.DataFrame,
        cfg: Dict[str, Any],
    ) -> Tuple[str, Dict[str, List[PatternEvent]], Dict[str, Any]]:
        """
        Calcule un vote SMC basique et renvoie (signal, events, extras).
        """
        if not cfg.get("smc_enabled", True):
            return "WAIT", {}, {}

        try:
            pivots = find_pivots(df, window=max(2, int(cfg["smc_pivot_window"])))
        except Exception:
            return "WAIT", {}, {}

        events: Dict[str, List[PatternEvent]] = {
            "bos": detect_bos(df, pivots=pivots),
            "choch": detect_choch(df, pivots=pivots),
            "fvg": detect_fvg(df, tolerance=cfg["smc_fvg_tol"]),
            "eqh": detect_equal_highs(df, tolerance=cfg["smc_eq_tolerance"]),
            "eql": detect_equal_lows(df, tolerance=cfg["smc_eq_tolerance"]),
            "order_blocks": detect_order_blocks(df, pivots=pivots),
            "breaker_blocks": detect_breaker_blocks(df, pivots=pivots),
            # PHASE 2: Nouveaux patterns SMC (2025-12-25)
            "inducement": detect_inducement(df, pivots=pivots),
            "liquidity_sweep": detect_liquidity_sweep(df),
            "mitigation_block": detect_mitigation_block(df, pivots=pivots),
        }

        # Scores directionnels - poids ajustes pour les nouveaux patterns
        weights = {
            "bos": 2.0,
            "choch": 2.0,
            "breaker_blocks": 1.5,
            "order_blocks": 1.0,
            "fvg": 0.75,
            "eqh": 0.5,
            "eql": 0.5,
            # Nouveaux patterns - poids eleves car ce sont des confirmations fortes
            "inducement": 2.5,          # Signal de reversal tres fort
            "liquidity_sweep": 2.0,     # Confirmation de manipulation
            "mitigation_block": 1.5,    # Zone d'entree validee
        }
        long_score = 0.0
        short_score = 0.0
        for name, evts in events.items():
            w = weights.get(name, 1.0)
            for evt in evts:
                if evt.direction == "LONG":
                    long_score += w
                elif evt.direction == "SHORT":
                    short_score += w

        signal = "WAIT"
        if long_score > short_score * 1.2 and long_score > 0.0:
            signal = "LONG"
        elif short_score > long_score * 1.2 and short_score > 0.0:
            signal = "SHORT"

        extra = {
            "long_score": round(long_score, 3),
            "short_score": round(short_score, 3),
            "equilibrium": compute_equilibrium(df),
            "ote_zone": smc_compute_ote_zone(df),
        }
        return signal, events, extra

    # --------------- Core ---------------
    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        tf = (timeframe or self.params.get("timeframe") or "M15").upper()
        cfg = self._cfg()
        need = max(cfg["lookback"], cfg["atr_period"] + 10)

        df = self._get_rates(tf, count=need)
        if df is None or len(df) < max(100, cfg["atr_period"] + 10):
            return {"signal": "WAIT", "reason": "no_data"}

        # Nettoyage
        df = df[["time", "open", "high", "low", "close"]].copy()
        df = df.dropna().reset_index(drop=True)
        if len(df) < max(50, cfg["atr_period"] + 5):
            return {"signal": "WAIT", "reason": "too_short"}

        # ATR
        df["atr"] = _atr(df, cfg["atr_period"])

        # Pivots
        is_ph, is_pl = _pivot_flags(df, cfg["swing_window"])
        pivH = df.loc[is_ph, ["high"]].copy()
        pivL = df.loc[is_pl, ["low"]].copy()

        if pivH.empty or pivL.empty:
            return {"signal": "WAIT", "reason": "no_pivots"}

        # Derniers 2 HH & LL
        last_highs = _last_n(pivH["high"].tolist(), 2)
        last_lows = _last_n(pivL["low"].tolist(), 2)

        # Indices (position dans df) des derniers pivot H/L
        last_high_idx = pivH.index.tolist()[-1]
        last_low_idx = pivL.index.tolist()[-1]

        close = float(df["close"].iloc[-1])
        atr = float(df["atr"].iloc[-1]) if not math.isnan(df["atr"].iloc[-1]) else None

        # Biais structurel
        bias = _trend_bias(last_highs, last_lows)  # "up" / "down" / None

        # Snapshot SMC (patterns avancés)
        smc_signal, smc_events, smc_meta = self._smc_snapshot(df, cfg)

        # BOS (break of structure) récent
        bos_up = close > float(last_highs[-1]) if last_highs else False
        bos_dn = close < float(last_lows[-1]) if last_lows else False

        # CHoCH: break dans le sens inverse du biais courant
        choch_up = bool(bias == "down" and bos_up)
        choch_dn = bool(bias == "up" and bos_dn)

        # FBO: si BOS tout récent mais le prix retourne dans la plage pivot en <= retest_bars
        fbo = False
        if bos_up or bos_dn:
            bars = cfg["retest_bars"]
            recent = df.iloc[-(bars + 1):]
            if bos_up:
                # faux breakout si on clôture sous le pivot high bactériologiquement vite
                if (recent["close"] < float(last_highs[-1])).any():
                    fbo = True
            if bos_dn:
                if (recent["close"] > float(last_lows[-1])).any():
                    fbo = True

        # Décision brute
        raw_signal = ""
        if fbo:
            raw_signal = "WAIT"
        elif choch_up or bos_up:
            raw_signal = "LONG"
        elif choch_dn or bos_dn:
            raw_signal = "SHORT"
        else:
            raw_signal = "WAIT"

        # Zone OTE + SL/TP
        price = None
        sl = None
        tp = None
        debug: Dict[str, Any] = {
            "tf": tf,
            "bias": bias,
            "bos_up": bos_up,
            "bos_dn": bos_dn,
            "choch_up": choch_up,
            "choch_dn": choch_dn,
            "fbo": fbo,
            "last_high": float(last_highs[-1]) if last_highs else None,
            "last_low": float(last_lows[-1]) if last_lows else None,
            "atr": atr,
            "smc_signal": smc_signal,
            "smc": {
                "events": self._serialize_events(smc_events),
                "meta": smc_meta,
            },
        }

        if raw_signal in ("LONG", "SHORT") and last_highs and last_lows and atr:
            # Détermine l'impulsion la plus récente (ordre des pivots)
            if last_high_idx > last_low_idx:
                # dernier swing marquant = High → mouvement haussier récent
                sw_low = float(last_lows[-1])
                sw_high = float(last_highs[-1])
                long_leg = True
            else:
                # dernier swing marquant = Low → mouvement baissier récent
                sw_low = float(last_lows[-1])
                sw_high = float(last_highs[-1])
                long_leg = False

            z1, z2, zmid = _ote_zone(long=raw_signal == "LONG", swing_low=sw_low, swing_high=sw_high)
            debug["ote_zone"] = (z1, z2, zmid)

            # Prix proposé = milieu de l'OTE
            price = float(zmid)

            # (2026-01-06) AMÉLIORATION: Utiliser compute_invalidation_sl pour le SL
            # au lieu de la simple formule pivot ± ATR*mult
            invalidation_result = None
            try:
                invalidation_result = compute_invalidation_sl(
                    df=df,
                    direction=raw_signal,
                    lookback=50,
                    buffer_pct=0.001
                )
                if invalidation_result and invalidation_result.get("sl_price"):
                    sl = float(invalidation_result["sl_price"])
                    debug["invalidation_sl"] = invalidation_result
            except Exception:
                invalidation_result = None

            # Fallback: SL par défaut si compute_invalidation_sl échoue
            sl_mult = float(cfg["sl_mult"])
            tp_mult = float(cfg["tp_mult"])

            if sl is None:
                if raw_signal == "LONG":
                    sl = float(min(sw_low, price) - sl_mult * atr)
                else:
                    sl = float(max(sw_high, price) + sl_mult * atr)

            # TP basé sur ATR (R:R ratio)
            if raw_signal == "LONG":
                risk = price - sl
                tp = float(price + tp_mult * risk) if risk > 0 else float(price + tp_mult * atr)
            else:
                risk = sl - price
                tp = float(price - tp_mult * risk) if risk > 0 else float(price - tp_mult * atr)

            # Sécurité : SL != TP et distance > 0
            if sl == tp or (abs(tp - price) < 1e-9) or (abs(price - sl) < 1e-9):
                sl = None
                tp = None

        out = {
            "signal": raw_signal,
            "price": price,
            "sl": sl,
            "tp": tp,
            "smc_signal": smc_signal,
            "smc_events": self._serialize_events(smc_events),
            "smc_meta": smc_meta,
            # Pour laisser une trace exploitable si besoin
            "debug": debug,
        }

        # Bonus : expose aussi un ATR spécifique au TF pour fallback orchestrateur
        try:
            out[f"ATR_{tf}"] = float(atr) if atr is not None else None
        except Exception:
            pass

        return out


# Alias rétrocompat (si tu importes encore PriceActionAgent depuis ce module)
PriceActionAgent = StructureAgent
