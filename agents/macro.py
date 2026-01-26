# agents/macro.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import os
import math
from datetime import datetime, timedelta, timezone
import pandas as pd


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(x, default: Optional[float] = None) -> Optional[float]:
    try:
        f = float(x)
        if math.isnan(f):
            return default
        return f
    except Exception:
        return default


class MacroAgent:
    """
    Agent macro/éco :
      - Lit un calendrier local (data/calendar.csv ou config/econ_calendar.yaml).
      - Bloque les entrées autour des événements High/Medium d’actifs concernés.
      - Garde-fous volat/spread (ATR spike, spread excessif).
      - Peut renvoyer un biais 'signal' (optionnel) s’il est posé dans la config.

    Sortie attendue par l’orchestrateur:
      {
        "block": bool,                 # True -> ORCH ajoute indicators["MACRO_BLOCK"]
        "signal": "LONG"/"SHORT"/"",   # Optionnel (sera routé comme 'fundamental')
        "reason": str,                 # Info debug
        "debug": {...}                 # Détails (spread, atr_ratio, events)
      }
    """

    def __init__(self, symbol: Optional[str] = None, mt5=None, profile: Optional[Dict[str, Any]] = None, **kwargs):
        self.symbol = (symbol or "").upper()
        self.mt5 = mt5
        self.profile = profile or {}
        self.params: Dict[str, Any] = (self.profile.get("agents", {}).get("macro", {}) if self.profile else {})

    # ---------------- Config ----------------
    def _cfg(self) -> Dict[str, Any]:
        p = self.params or {}
        # fenêtres autour d’un event (minutes)
        pre_min = int(p.get("pre_window_min", p.get("pre_min", 30)))
        post_min = int(p.get("post_window_min", p.get("post_min", 30)))
        # impacts qui bloquent (met "high" uniquement si tu veux être plus permissif)
        block_impacts = [s.lower() for s in p.get("block_impacts", ["high", "medium"])]
        # garde-fous volat/spread
        max_spread_pts = float(p.get("max_spread_points", 0))         # 0 = ignore
        atr_tf = str(p.get("atr_timeframe", "M5")).upper()
        atr_period = int(p.get("atr_period", 14))
        atr_spike_ratio = float(p.get("atr_spike_ratio", 2.0))        # ATR courant / ATR_moy > ratio => block
        # biais (optionnel): "LONG" | "SHORT" | ""
        bias = str(p.get("bias", "")).upper()
        # fichiers calendrier
        csv_path = p.get("calendar_csv", os.path.join("data", "calendar.csv"))
        yaml_path = p.get("calendar_yaml", os.path.join("config", "econ_calendar.yaml"))

        return {
            "pre_min": pre_min,
            "post_min": post_min,
            "block_impacts": block_impacts,
            "max_spread_pts": max_spread_pts,
            "atr_tf": atr_tf,
            "atr_period": atr_period,
            "atr_spike_ratio": atr_spike_ratio,
            "bias": bias if bias in ("LONG", "SHORT") else "",
            "csv_path": csv_path,
            "yaml_path": yaml_path,
        }

    # ---------------- Calendar I/O ----------------
    def _load_calendar_rows(self, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        # 1) CSV (facile à éditer)
        csv_path = cfg["csv_path"]
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                for _, r in df.iterrows():
                    rows.append(
                        {
                            "time_utc": str(r.get("time_utc") or r.get("time")),
                            "affects": str(r.get("affects") or ""),
                            "impact": str(r.get("impact") or "").lower(),
                            "title": str(r.get("title") or ""),
                        }
                    )
            except Exception:
                pass

        # 2) YAML (optionnel)
        try:
            import yaml  # local, pas d'accès réseau
            if os.path.exists(cfg["yaml_path"]):
                with open(cfg["yaml_path"], encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for it in data.get("events", []):
                    rows.append(
                        {
                            "time_utc": str(it.get("time_utc") or it.get("time")),
                            "affects": ",".join(it.get("affects", [])),
                            "impact": str(it.get("impact") or "").lower(),
                            "title": str(it.get("title") or ""),
                        }
                    )
        except Exception:
            pass

        return rows

    def _affect_keys_for_symbol(self) -> List[str]:
        s = self.symbol
        # clefs d’affectation génériques pour matcher les events
        if s in ("EURUSD",):
            return ["EURUSD", "EUR", "USD", "FX", "ALL"]
        if s in ("XAUUSD",):
            return ["XAUUSD", "XAU", "GOLD", "USD", "FX", "ALL"]
        if s in ("BTCUSD", "LTCUSD", "ETHUSD", "BNBUSD", "ADAUSD", "SOLUSD"):
            return [s, "BTC", "CRYPTO", "USD", "ALL"]
        return [s, "USD", "FX", "ALL"]

    def _in_event_window(self, now: datetime, evt_time: datetime, pre_min: int, post_min: int) -> bool:
        return (evt_time - timedelta(minutes=pre_min)) <= now <= (evt_time + timedelta(minutes=post_min))

    # ---------------- Market helpers ----------------
    def _get_point(self) -> float:
        try:
            inst = (self.profile.get("instrument") or {})
            pt = float(inst.get("point", 0.0))
            return pt if pt > 0 else 0.0
        except Exception:
            return 0.0

    def _get_spread_points(self) -> Optional[float]:
        """Spread en 'points' broker, si possible."""
        if not self.mt5 or not hasattr(self.mt5, "get_tick"):
            return None
        try:
            broker_symbol = self.profile.get("instrument", {}).get("broker_symbol") or self.symbol
            tick = self.mt5.get_tick(broker_symbol)
            point = self._get_point() or 0.0
            if not tick or point <= 0:
                return None
            # accept dict or namedtuple-like
            bid = _safe_float(getattr(tick, "bid", None) if not isinstance(tick, dict) else tick.get("bid"))
            ask = _safe_float(getattr(tick, "ask", None) if not isinstance(tick, dict) else tick.get("ask"))
            if bid is None or ask is None:
                return None
            return abs(ask - bid) / point
        except Exception:
            return None

    def _atr(self, tf: str, period: int) -> Optional[float]:
        if not self.mt5 or not hasattr(self.mt5, "get_rates"):
            return None
        try:
            bars = self.mt5.get_rates(self.symbol, tf, count=period + 20)
            if not bars or len(bars) < period + 2:
                return None
            df = pd.DataFrame(bars)
            need = {"high", "low", "close"}
            if not need.issubset(df.columns):
                return None

            high = df["high"].astype(float)
            low = df["low"].astype(float)
            close = df["close"].astype(float)
            prev_close = close.shift(1)

            tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean().iloc[-1]
            if pd.isna(atr):
                return None
            return float(atr)
        except Exception:
            return None

    def _atr_ratio(self, tf: str, period: int) -> Optional[float]:
        """ATR / moyenne ATR (20) → spike ratio."""
        if not self.mt5 or not hasattr(self.mt5, "get_rates"):
            return None
        try:
            need = max(20, period) * 6 + 10
            bars = self.mt5.get_rates(self.symbol, tf, count=need)
            if not bars or len(bars) < period + 25:
                return None
            df = pd.DataFrame(bars)
            need_cols = {"high", "low", "close"}
            if not need_cols.issubset(df.columns):
                return None

            high = df["high"].astype(float)
            low = df["low"].astype(float)
            close = df["close"].astype(float)
            prev_close = close.shift(1)

            tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            cur = atr.iloc[-1]
            base = atr.rolling(window=20).mean().iloc[-1]
            if pd.isna(cur) or pd.isna(base) or base <= 0:
                return None
            return float(cur / base)
        except Exception:
            return None

    # ---------------- Core ----------------
    def generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]:
        cfg = self._cfg()
        now = _now_utc()

        # 1) Lire le calendrier local
        rows = self._load_calendar_rows(cfg)
        affects_keys = [k.upper() for k in self._affect_keys_for_symbol()]
        block_by_calendar = False
        matched_events: List[Dict[str, Any]] = []
        reason_parts: List[str] = []

        for r in rows:
            try:
                t = r.get("time_utc") or r.get("time")
                if not t:
                    continue
                evt_time = datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue

            # filtrer par 'affects'
            raw_affects = (r.get("affects") or "").upper()
            if raw_affects:
                tags = [a.strip() for a in raw_affects.split(",") if a.strip()]
            else:
                tags = ["ALL"]

            impact = (r.get("impact") or "").lower().strip()  # "high" | "medium" | "low"...
            title = r.get("title") or ""

            if not any(a in affects_keys for a in tags):
                continue

            # fenêtre block ?
            if impact in cfg["block_impacts"] and self._in_event_window(now, evt_time, cfg["pre_min"], cfg["post_min"]):
                block_by_calendar = True

            matched_events.append(
                {
                    "time_utc": evt_time.isoformat(),
                    "impact": impact,
                    "title": title,
                    "affects": tags,
                    "in_window": self._in_event_window(now, evt_time, cfg["pre_min"], cfg["post_min"]),
                }
            )

        if block_by_calendar:
            reason_parts.append("calendar_window")

        # 2) Spread guard
        spread_pts = self._get_spread_points()
        spread_block = False
        if cfg["max_spread_pts"] > 0 and spread_pts is not None and spread_pts > cfg["max_spread_pts"]:
            spread_block = True
            reason_parts.append(f"spread>{cfg['max_spread_pts']}pts")

        # 3) ATR spike guard
        atr_ratio = self._atr_ratio(cfg["atr_tf"], cfg["atr_period"])
        atr_block = False
        if atr_ratio is not None and atr_ratio >= cfg["atr_spike_ratio"]:
            atr_block = True
            reason_parts.append(f"ATRx{atr_ratio:.2f}>{cfg['atr_spike_ratio']:.2f}")

        # 4) Décision block
        do_block = block_by_calendar or spread_block or atr_block

        # 5) (Optionnel) biais fondamental simple via config (on ne devine rien ici)
        signal = cfg["bias"]  # "LONG"/"SHORT"/""

        out = {
            "block": bool(do_block),
            "signal": signal,
            "reason": ",".join(reason_parts) if reason_parts else "",
            "debug": {
                "affects_keys": affects_keys,
                "matched_events": matched_events[-10:],  # les 10 derniers matchés
                "spread_points": spread_pts,
                "atr_ratio": atr_ratio,
                "cfg": {
                    "pre_min": cfg["pre_min"],
                    "post_min": cfg["post_min"],
                    "block_impacts": cfg["block_impacts"],
                    "max_spread_pts": cfg["max_spread_pts"],
                    "atr_tf": cfg["atr_tf"],
                    "atr_period": cfg["atr_period"],
                    "atr_spike_ratio": cfg["atr_spike_ratio"],
                    "bias": cfg["bias"],
                },
                "now_utc": now.isoformat(),
            },
        }
        return out

# NOTE: FundamentalAgent est défini séparément dans agents/fundamental.py
# MacroAgent gère les conditions macro (spread, ATR, heures) + calendrier économique Finnhub
