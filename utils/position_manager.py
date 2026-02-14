# utils/position_manager.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
import os
import json
import math
import time
import threading
from datetime import datetime, timezone

import pandas as pd

# =============================================================================
# GLOBAL LOCK pour éviter les opérations MT5 simultanées (fix 2025-12-17)
# Problème: Quand plusieurs cryptos atteignent TP1 en même temps, les closes
#           partiels peuvent échouer ou ne pas être enregistrés correctement.
# Solution: Lock global + délai minimum entre opérations MT5.
# =============================================================================
_MT5_OPERATION_LOCK = threading.Lock()
_LAST_MT5_OPERATION_TIME: float = 0.0
_MT5_OPERATION_DELAY_SEC: float = 1.5  # Délai minimum entre opérations MT5

# Alias pour compatibilité
_PARTIAL_CLOSE_LOCK = _MT5_OPERATION_LOCK
_LAST_PARTIAL_CLOSE_TIME: float = 0.0
_PARTIAL_CLOSE_DELAY_SEC: float = 2.0  # Délai spécifique pour closes partiels

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:
    mt5 = None

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.mt5_client import MT5Client
except Exception:
    MT5Client = None  # type: ignore
# ------------------------------- helpers --------------------------------
def _canon_to_broker(sym: str) -> str:
        """Convertit un symbole canonique vers le symbole broker si nécessaire."""
        s = (sym or "").upper()
        # Pas de mapping nécessaire actuellement
        return s

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

def _atr_from_rates(df: pd.DataFrame, period: int) -> Optional[float]:
    try:
        if df is None or df.empty:
            return None
        if not all(c in df.columns for c in ("high", "low", "close")):
            return None
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=int(period)).mean().iloc[-1]
        if pd.isna(atr):
            return None
        return float(atr)
    except Exception:
        return None

def _compute_rr(side: str, entry: float, sl: float, tp: float, price: float) -> Optional[float]:
    """R multiple courant par rapport au SL/TP proposés (approx)."""
    try:
        if side == "BUY":
            risk = max(entry - sl, 1e-9)
            reward_now = price - entry
        else:
            risk = max(sl - entry, 1e-9)
            reward_now = entry - price
        return float(reward_now / risk)
    except Exception:
        return None

def _round_to_step(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor((x + 1e-12) / step) * step

# ------------------------------- state ----------------------------------
_STATE_PATH = os.path.join("data", "pm_state.json")

def _load_state() -> Dict[str, Any]:
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def _save_state(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ----------------------------- Market Hours -------------------------------
# Horaires de fermeture des marchés (heure UTC)
# Format: {symbole_pattern: (heure_fermeture, minute_fermeture, jours_trading)}
# jours_trading: 0=Lundi, 4=Vendredi, None=24/7
MARKET_CLOSE_TIMES = {
    # Indices - ferment à 21:00 UTC (22:00 CET) du lundi au vendredi
    "GER40": (21, 0, [0, 1, 2, 3, 4]),      # DAX
    "DJ30": (21, 0, [0, 1, 2, 3, 4]),       # Dow Jones
    "NAS100": (21, 0, [0, 1, 2, 3, 4]),     # Nasdaq
    "US500": (21, 0, [0, 1, 2, 3, 4]),      # S&P 500
    # Forex - ferme vendredi 21:00 UTC (pas de week-end)
    "EURUSD": (21, 0, [4]),                 # Ferme vendredi soir
    "GBPUSD": (21, 0, [4]),
    "USDJPY": (21, 0, [4]),
    "AUDUSD": (21, 0, [4]),
    # Matières premières
    "CL-OIL": (21, 0, [0, 1, 2, 3, 4]),     # Pétrole
    "XAUUSD": (21, 0, [4]),                 # Or - ferme vendredi
    "XAGUSD": (21, 0, [4]),                 # Argent - ferme vendredi
    # Cryptos - 24/7, pas de fermeture
}

# ----------------------------- dataclasses -------------------------------
@dataclass
class PMBreakEven:
    rr: float = 1.0
    offset_points: float = 0.0

@dataclass
class PMPartial:
    rr: float
    close_frac: float

@dataclass
class PMTrailing:
    enabled: bool = True
    start_rr: float = 1.2
    atr_timeframe: str = "M5"
    atr_period: int = 14
    atr_mult: float = 1.6
    lock_rr: float = 0.2  # ne jamais revenir sous +lock_rr


# ----------------------------- main class --------------------------------
class PositionManager:
    """
    Gère BE / Partials / Trailing pour les positions ouvertes du symbole.
    - Lecture des paramètres depuis profiles.yaml: profiles.<SYMBOL>.orchestrator.position_manager
    - Persiste l’état par ticket dans data/pm_state.json pour éviter les répétitions
    - Utilise MT5Client si dispo, sinon fallback MetaTrader5 direct
    """

    def __init__(self, mt5_client: Any, symbol: str, profile: Dict[str, Any], notifier=None):
        self.mt5 = mt5_client
        self.symbol_canon = symbol
        self.profile = profile
        self._notifier = notifier
        # wrapper de notification sécurisé
        def _notify(tag: str, payload: dict):
            try:
                if callable(self._notifier):
                    self._notifier(tag, payload)
            except Exception:
                pass
        self._notify = _notify
        # persistance des positions ouvertes détectées
        self._open_state_path = os.path.join("data", "open_positions.json")
        self.mt5c = mt5_client
        inst = (self.profile.get("instrument") or {}) if isinstance(self.profile, dict) else {}
        self.broker_symbol = inst.get("broker_symbol") or _canon_to_broker(self.symbol_canon)
        self.point = float(inst.get("point", 0.01) or 0.01)
        self.min_lot = float(inst.get("min_lot", 0.01) or 0.01)
        self.lot_step = float(inst.get("lot_step", 0.01) or 0.01)
        self._state: Dict[str, Any] = _load_state()
        pm_cfg = ((self.profile.get("orchestrator") or {}).get("position_manager") or {}) if isinstance(self.profile, dict) else {}
        self.enabled = bool(pm_cfg.get("enabled", True))
        be_cfg = pm_cfg.get("break_even") or {}
        self.be = PMBreakEven(
            rr=float(be_cfg.get("rr", 1.0)),
            offset_points=float(be_cfg.get("offset_points", 0.0)),
        )
        partials_cfg = pm_cfg.get("partials") or []
        self.partials = [
            PMPartial(rr=float(p.get("rr")), close_frac=float(p.get("close_frac", 0.5)))
            for p in partials_cfg
            if isinstance(p, dict) and p.get("rr") is not None
        ]
        self.partials.sort(key=lambda p: p.rr)
        trail_cfg = pm_cfg.get("trailing") or {}
        self.trailing = PMTrailing(
            enabled=bool(trail_cfg.get("enabled", True)),
            start_rr=float(trail_cfg.get("start_rr", 1.2)),
            atr_timeframe=str(trail_cfg.get("atr_timeframe", "M5")),
            atr_period=int(trail_cfg.get("atr_period", 14)),
            atr_mult=float(trail_cfg.get("atr_mult", 1.6)),
            lock_rr=float(trail_cfg.get("lock_rr", 0.2)),
        )

        # Configuration fermeture avant clôture marché
        close_before_cfg = pm_cfg.get("close_before_market_close") or {}
        self.close_before_enabled = bool(close_before_cfg.get("enabled", True))
        self.close_before_minutes = int(close_before_cfg.get("minutes_before", 30))

    def _load_open_state(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self._open_state_path):
                with open(self._open_state_path, encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_open_state(self, st: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._open_state_path), exist_ok=True)
            with open(self._open_state_path, "w", encoding="utf-8") as f:
                json.dump(st, f)
        except Exception:
            pass
    # ---------------------------- MT5 helpers ----------------------------
    def _positions_get(self) -> List[Any]:
        try:
            if self.mt5c and hasattr(self.mt5c, "positions_get"):
                poss = self.mt5c.positions_get(symbol=self.broker_symbol)
                if poss is not None:
                    return list(poss)
        except Exception:
            pass
        try:
            if mt5:
                poss = mt5.positions_get(symbol=self.broker_symbol)
                return list(poss or [])
        except Exception:
            pass
        return []

    def _modify_sl_tp(self, ticket: int, sl: Optional[float], tp: Optional[float]) -> bool:
        """
        Modifie SL/TP d'une position avec lock global.
        Fix 2025-12-17: Évite les modifications simultanées sur plusieurs positions.
        """
        global _LAST_MT5_OPERATION_TIME

        with _MT5_OPERATION_LOCK:
            # Petit délai entre opérations MT5
            now = time.time()
            elapsed = now - _LAST_MT5_OPERATION_TIME
            if elapsed < _MT5_OPERATION_DELAY_SEC:
                wait_time = _MT5_OPERATION_DELAY_SEC - elapsed
                time.sleep(wait_time)

            try:
                if self.mt5c and hasattr(self.mt5c, "modify_position_sl_tp"):
                    result = bool(self.mt5c.modify_position_sl_tp(ticket=ticket, sl=sl, tp=tp))
                    if result:
                        _LAST_MT5_OPERATION_TIME = time.time()
                    return result
            except Exception:
                pass

            # fallback natif
            try:
                if not mt5:
                    return False
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": int(ticket),
                    "sl": sl if sl else 0.0,
                    "tp": tp if tp else 0.0,
                    "deviation": int((self.profile.get("deviation") or 30)),
                }
                res = mt5.order_send(request)
                result = bool(res) and int(getattr(res, "retcode", -1)) == getattr(mt5, "TRADE_RETCODE_DONE", 10009)
                if result:
                    _LAST_MT5_OPERATION_TIME = time.time()
                return result
            except Exception:
                return False

    def _close_partial(self, ticket: int, volume_close: float) -> bool:
        """
        Ferme partiellement une position avec lock global et délai.
        Fix 2025-12-17: Évite les closes simultanés sur plusieurs cryptos.
        """
        global _LAST_PARTIAL_CLOSE_TIME

        # Acquérir le lock global pour éviter les closes simultanés
        with _PARTIAL_CLOSE_LOCK:
            # Vérifier le délai depuis le dernier close
            now = time.time()
            elapsed = now - _LAST_PARTIAL_CLOSE_TIME
            if elapsed < _PARTIAL_CLOSE_DELAY_SEC:
                wait_time = _PARTIAL_CLOSE_DELAY_SEC - elapsed
                logger.info(f"[PM] Attente {wait_time:.1f}s avant close partial (anti-collision)")
                time.sleep(wait_time)

            # Exécuter le close partial
            result = False
            try:
                if self.mt5c and hasattr(self.mt5c, "close_partial"):
                    result = bool(self.mt5c.close_partial(ticket=ticket, volume=volume_close))
                    if result:
                        _LAST_PARTIAL_CLOSE_TIME = time.time()
                        return True
            except Exception as e:
                logger.warning(f"[PM] close_partial via mt5c failed: {e}")

            # fallback natif: position_close_partially
            try:
                if mt5 and hasattr(mt5, "position_close_partial"):
                    r = mt5.position_close_partial(ticket, volume_close)
                    result = bool(r)
                    if result:
                        _LAST_PARTIAL_CLOSE_TIME = time.time()
                    return result
            except Exception as e:
                logger.warning(f"[PM] close_partial via mt5 native failed: {e}")

            return False

    def _get_rates(self, timeframe: str, count: int = 200) -> Optional[pd.DataFrame]:
        try:
            if self.mt5c and hasattr(self.mt5c, "get_rates"):
                bars = self.mt5c.get_rates(self.broker_symbol, timeframe, count=count)
                if bars:
                    return pd.DataFrame(bars)
        except Exception:
            pass
        try:
            if mt5:
                tf_map = {
                    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1
                }
                tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
                rates = mt5.copy_rates_from_pos(self.broker_symbol, tf, 0, count)
                if rates:
                    return pd.DataFrame(list(rates))
        except Exception:
            pass
        return None

    # ---------------------------- Market Close helpers ----------------------------
    def _get_market_close_time(self) -> Optional[Tuple[int, int, List[int]]]:
        """Retourne (heure, minute, jours) de fermeture pour ce symbole, ou None si 24/7."""
        sym = self.symbol_canon.upper()
        return MARKET_CLOSE_TIMES.get(sym)

    def _is_near_market_close(self) -> bool:
        """Vérifie si on est dans les X minutes avant la fermeture du marché."""
        if not self.close_before_enabled:
            return False

        close_info = self._get_market_close_time()
        if close_info is None:
            return False  # Marché 24/7 (cryptos)

        close_hour, close_minute, trading_days = close_info
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Lundi, 4=Vendredi

        # Vérifier si aujourd'hui est un jour où le marché ferme
        if weekday not in trading_days:
            return False

        # Calculer l'heure de fermeture
        close_time = now.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)

        # Calculer la différence en minutes
        diff_seconds = (close_time - now).total_seconds()
        diff_minutes = diff_seconds / 60

        # Si on est dans la fenêtre de fermeture (entre 0 et close_before_minutes avant)
        return 0 <= diff_minutes <= self.close_before_minutes

    def _close_position_full(self, ticket: int, volume: float, side: str) -> bool:
        """Ferme entièrement une position."""
        try:
            if not mt5:
                return False

            # Déterminer le type d'ordre inverse
            if side == "BUY":
                order_type = mt5.ORDER_TYPE_SELL
                tick = mt5.symbol_info_tick(self.broker_symbol)
                price = tick.bid if tick else 0
            else:
                order_type = mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(self.broker_symbol)
                price = tick.ask if tick else 0

            if not price or price <= 0:
                logger.warning(f"[PM] Cannot get price to close position {ticket}")
                return False

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": int(ticket),
                "symbol": self.broker_symbol,
                "volume": float(volume),
                "type": order_type,
                "price": price,
                "deviation": 30,
                "magic": 0,
                "comment": "close_before_market",
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[PM] Position {ticket} closed before market close")
                return True
            else:
                err = result.comment if result else "Unknown"
                logger.warning(f"[PM] Failed to close position {ticket}: {err}")
                return False

        except Exception as e:
            logger.warning(f"[PM] Error closing position {ticket}: {e}")
            return False

    def _close_positions_before_market_close(self) -> int:
        """Ferme toutes les positions si on est proche de la fermeture du marché.
        Retourne le nombre de positions fermées."""
        if not self._is_near_market_close():
            return 0

        positions = self._positions_get()
        if not positions:
            return 0

        closed_count = 0
        close_info = self._get_market_close_time()
        close_hour, close_minute, _ = close_info or (0, 0, [])

        for p in positions:
            try:
                ticket = int(getattr(p, "ticket", 0) or 0)
                volume = float(getattr(p, "volume", 0) or 0)
                side = "BUY" if int(getattr(p, "type", 0)) == 0 else "SELL"
                profit = float(getattr(p, "profit", 0) or 0)

                if ticket <= 0 or volume <= 0:
                    continue

                logger.info(
                    f"[PM] Closing {self.symbol_canon} position {ticket} before market close "
                    f"({close_hour}:{close_minute:02d} UTC). Current P&L: {profit:+.2f}"
                )

                if self._close_position_full(ticket, volume, side):
                    closed_count += 1
                    self._notify("CLOSE_TRADE", {
                        "symbol": self.symbol_canon,
                        "ticket": ticket,
                        "result": "MARKET_CLOSE",
                        "pnl_ccy": f"{profit:+.2f}",
                        "pnl_pips": "N/A",
                        "duration": "N/A",
                        "rr": "N/A",
                        "mfe": "N/A",
                        "mae": "N/A",
                    })

            except Exception as e:
                logger.warning(f"[PM] Error processing position for market close: {e}")
                continue

        if closed_count > 0:
            logger.info(f"[PM] Closed {closed_count} position(s) before market close for {self.symbol_canon}")

        return closed_count

    # ---------------------------- state per ticket -----------------------
    def _tk(self, ticket: int) -> str:
        return f"{self.symbol_canon}:{ticket}"

    def _get_tstate(self, ticket: int) -> Dict[str, Any]:
        return self._state.get(self._tk(ticket), {"partials_done": [], "be_done": False, "trail_active": False})

    def _set_tstate(self, ticket: int, st: Dict[str, Any]) -> None:
        self._state[self._tk(ticket)] = st
        _save_state(self._state)

    # ---------------------------- core rules -----------------------------
    def _apply_break_even(
        self,
        side: str,
        entry: float,
        sl: float,
        price: float,
        *,
        force: bool = False,
    ) -> Optional[float]:
        """
        Retourne un nouveau SL si le passage à BE est requis, sinon None.
        """
        if not force:
            rr = _compute_rr(side, entry, sl, tp=entry, price=price)  # TP fictif=entry pour calculer R atteint
            if rr is None or rr < float(self.be.rr):
                return None
        offs = float(self.be.offset_points or 0.0) * self.point
        return (entry + offs) if side == "BUY" else (entry - offs)

    def _apply_partials(self, ticket: int, volume: float, rr_now: float) -> Tuple[float, bool]:
        """
        Tente de fermer des portions selon partials[]. Met à jour l'état. Retourne (volume restant, partial déclenché).
        """
        st = self._get_tstate(ticket)
        done = set(st.get("partials_done", []))
        vol_left = float(volume)
        partial_hit = False

        for p in self.partials:
            if p.rr in done:
                continue
            if rr_now >= float(p.rr):
                # calc vol à fermer
                to_close = max(0.0, float(p.close_frac) * vol_left)
                to_close = _round_to_step(to_close, self.lot_step)
                if to_close >= self.min_lot and to_close < vol_left - self.lot_step / 2:
                    ok = self._close_partial(ticket, to_close)
                    if ok:
                        vol_left = max(self.min_lot, vol_left - to_close)
                        done.add(p.rr)
                        st["partials_done"] = sorted(list(done))
                        self._set_tstate(ticket, st)
                        logger.info(f"[PM] Partial {self.symbol_canon} ticket={ticket} rr>={p.rr} close={to_close}")
                        partial_hit = True
        return vol_left, partial_hit

    def _apply_trailing(self, side: str, entry: float, sl: float, price: float, atr: float) -> Optional[float]:
        """
        Trailing ATR : nouveau SL proposé si > SL actuel (buy) ou < SL actuel (sell).
        - start_rr: n’active le trailing que si R courant >= start_rr
        - lock_rr: ne jamais redescendre sous +lock_rr
        """
        try:
            rr_now = _compute_rr(side, entry, sl, tp=entry, price=price)
            if rr_now is None or rr_now < float(self.trailing.start_rr):
                return None

            mult = float(self.trailing.atr_mult)
            delta = max(atr * mult, 1e-9)

            if side == "BUY":
                new_sl = price - delta
                # lock_rr: calculer le SL min garanti (entry + lock_rr * risk)
                risk = max(entry - sl, 1e-9)
                lock_sl = entry + float(self.trailing.lock_rr) * risk
                new_sl = max(new_sl, lock_sl, sl)  # jamais en-dessous de l’actuel
            else:
                new_sl = price + delta
                risk = max(sl - entry, 1e-9)
                lock_sl = entry - float(self.trailing.lock_rr) * risk
                new_sl = min(new_sl, lock_sl, sl)  # jamais au-dessus de l’actuel
            return float(new_sl)
        except Exception:
            return None

    # ---------------------------- public entry ---------------------------
    def manage_open_positions(self) -> None:
        if not self.enabled:
            return

        # PRIORITÉ: Fermer les positions avant la clôture du marché
        closed_before_market = self._close_positions_before_market_close()
        if closed_before_market > 0:
            return  # Positions fermées, pas besoin de continuer

        prev = self._load_open_state().get(self.symbol_canon, {})
        current: Dict[str, dict] = {}
        try:
            positions = self._positions_get()
        except Exception:
            positions = []
        for p in positions or []:
            try:
                ticket = int(getattr(p, "ticket", 0) or 0)
                current[str(ticket)] = {
                    "entry": float(getattr(p, "price_open", 0.0) or 0.0),
                    "sl": float(getattr(p, "sl", 0.0) or 0.0),
                    "tp": float(getattr(p, "tp", 0.0) or 0.0),
                    "side": "BUY" if getattr(p, "type", 0) in (0, mt5.ORDER_TYPE_BUY if mt5 else 0) else "SELL",
                    "time": int(getattr(p, "time", 0) or 0),
                }
            except Exception:
                continue
        # tickets fermés = présents avant, absents maintenant
        closed_ids = [int(k) for k in prev.keys() if k not in current]
        if closed_ids:
            try:
                from datetime import datetime, timedelta, timezone as _tz
                end = datetime.now(_tz.utc); start = end - timedelta(days=2)
                deals = mt5.history_deals_get(start, end) if mt5 else []
            except Exception:
                deals = []
            for tk in closed_ids:
                tk_deals = [d for d in (deals or []) if int(getattr(d, "position_id", 0) or 0) == int(tk)
                            or int(getattr(d, "order", 0) or 0) == int(tk)]
                pnl = sum(float(getattr(d, "profit", 0.0) or 0.0) for d in tk_deals)
                close_time = max((int(getattr(d, "time", 0) or 0) for d in tk_deals), default=None)
                entry = float(prev[str(tk)].get("entry") or 0.0)
                side = prev[str(tk)].get("side")
                point = float(getattr(mt5.symbol_info(self.broker_symbol), "point", 0.01)) if mt5 else 0.01
                px_close = next((float(getattr(d, "price") or 0) for d in tk_deals if getattr(d, "price", None)), None)
                pnl_pips = ((px_close - entry)/point if side=="BUY" else (entry - px_close)/point) if (px_close and entry) else 0.0
                dur = "N/A"
                try:
                    t_open = int(prev[str(tk)].get("time") or 0)
                    if t_open and close_time:
                        mins = max(0, int(close_time) - int(t_open)) // 60
                        dur = f"{mins//60}h{mins%60:02d}"
                except Exception:
                    pass
                result = "TP" if pnl > 0 else ("SL" if pnl < 0 else "BE/Manuel")
                self._notify("CLOSE_TRADE", {
                    "symbol": self.symbol_canon, "ticket": tk, "result": result,
                    "pnl_ccy": f"{pnl:+.2f}", "pnl_pips": f"{pnl_pips:+.1f}",
                    "duration": dur, "rr": "N/A", "mfe": "N/A", "mae": "N/A"
                })

            # (audit fev2026) Nettoyage positions fantômes dans pm_state
            cleaned = 0
            for tk in closed_ids:
                for key_fmt in [f"{self.symbol_canon}:{tk}", str(tk)]:
                    if key_fmt in self._state:
                        del self._state[key_fmt]
                        cleaned += 1
            if cleaned > 0:
                _save_state(self._state)
                logger.info(f"[PM] Cleaned ghost positions from pm_state: {cleaned} entries for {self.symbol_canon} (tickets: {closed_ids})")

        # persister l'état courant
        state = self._load_open_state(); state[self.symbol_canon] = current; self._save_open_state(state)
        try:
            positions = self._positions_get()
            if not positions:
                return

            # Préparer ATR si trailing activé
            atr_val: Optional[float] = None
            if self.trailing.enabled:
                df = self._get_rates(self.trailing.atr_timeframe, count=max(60, self.trailing.atr_period + 5))
                atr_val = _atr_from_rates(df, self.trailing.atr_period) if df is not None else None

            for p in positions:
                try:
                    typ = int(getattr(p, "type", 0))  # 0 BUY, 1 SELL
                    side = "BUY" if typ == 0 else "SELL"
                    ticket = int(getattr(p, "ticket", getattr(p, "identifier", 0)) or 0)
                    entry = _safe_float(getattr(p, "price_open", None))
                    sl    = _safe_float(getattr(p, "sl", None))
                    tp    = _safe_float(getattr(p, "tp", None))
                    price = _safe_float(getattr(p, "price_current", None))
                    volume= _safe_float(getattr(p, "volume", None))

                    if None in (entry, sl, price, volume) or ticket <= 0:
                        continue

                    # RR actuel (si TP absent, on utilise entry pour RR BE/partials)
                    rr_now = _compute_rr(side, entry, sl, tp or entry, price) or 0.0

                    # ---- PARTIALS
                    partial_hit = False
                    if self.partials and volume and rr_now >= min(pp.rr for pp in self.partials):
                        volume, partial_hit = self._apply_partials(ticket, volume, rr_now)

                    st = self._get_tstate(ticket)
                    force_be = partial_hit and not st.get("be_done", False)

                    # ---- BREAK-EVEN
                    new_sl_be = self._apply_break_even(side, entry, sl, price, force=force_be)
                    if new_sl_be is not None and ((side == "BUY" and new_sl_be > sl) or (side == "SELL" and new_sl_be < sl)):
                        if self._modify_sl_tp(ticket, new_sl_be, tp):
                            sl = new_sl_be
                            st = self._get_tstate(ticket)
                            st["be_done"] = True
                            self._set_tstate(ticket, st)
                            self._notify("MOVE_BE", {"symbol": self.symbol_canon, "detail": f"ticket={ticket} SL->{new_sl_be:.5f}"})


                    # ---- TRAILING
                    if self.trailing.enabled and atr_val and atr_val > 0:
                        new_sl_tr = self._apply_trailing(side, entry, sl, price, atr_val)
                        if new_sl_tr is not None and ((side == "BUY" and new_sl_tr > sl) or (side == "SELL" and new_sl_tr < sl)):
                            if self._modify_sl_tp(ticket, new_sl_tr, tp):
                                sl = new_sl_tr
                                st = self._get_tstate(ticket)
                                st["trail_active"] = True
                                self._set_tstate(ticket, st)
                                self._notify("TRAILING_SL_UPDATE", {"symbol": self.symbol_canon, "detail": f"ticket={ticket} SL->{new_sl_tr:.5f}"})

                except Exception as e:
                    logger.warning(f"[PM] manage position error: {e}")

        except Exception as e:
            logger.warning(f"[PM] manage_open_positions failed: {e}")
