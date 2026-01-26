# backtest/agent_backtest.py
from __future__ import annotations
import importlib
import yaml
import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List

from utils.mt5_client import MT5Client
from utils.indicators import compute_atr

# Import optionnel de MetaTrader5 (Windows uniquement)
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

@dataclass
class BTResult:
    trades: List[float]
    nb_trades: int
    pnl: float
    sharpe: float
    profit_factor: float
    max_dd: float
    winrate: float
    csv_path: Optional[str]

class FakeMT5Client:
    def __init__(self, df_by_tf: Dict[str, pd.DataFrame]):
        self.df_by_tf = df_by_tf
        self._pos = 0
        self.default_symbol = None

    # Constantes MT5 timeframes (hardcodées pour compatibilité sans MT5)
    TIMEFRAME_M1  = mt5.TIMEFRAME_M1 if mt5 else 1
    TIMEFRAME_M5  = mt5.TIMEFRAME_M5 if mt5 else 5
    TIMEFRAME_M15 = mt5.TIMEFRAME_M15 if mt5 else 15
    TIMEFRAME_M30 = mt5.TIMEFRAME_M30 if mt5 else 30
    TIMEFRAME_H1  = mt5.TIMEFRAME_H1 if mt5 else 16385
    TIMEFRAME_H4  = mt5.TIMEFRAME_H4 if mt5 else 16388
    TIMEFRAME_D1  = mt5.TIMEFRAME_D1 if mt5 else 16408

    @staticmethod
    def _tf_key(tf) -> str:
        # Mapping timeframe → string
        TF_MAP = {
            1: "M1", 5: "M5", 15: "M15", 30: "M30",
            16385: "H1", 16388: "H4", 16408: "D1"
        }
        return tf if isinstance(tf, str) else TF_MAP.get(tf, "H1")

    def set_pos(self, pos: int):
        self._pos = pos

    def copy_rates(self, symbol: str, timeframe, count: int = 200):
        key = self._tf_key(timeframe)
        df = self.df_by_tf[key]
        end = self._pos + 1
        start = max(0, end - count)
        sub = df.iloc[start:end]
        return sub.to_records(index=False)

    def fetch_ohlc(self, symbol: str, timeframe, n=1000):
        return self.copy_rates(symbol, timeframe, n)

    def copy_rates_range(self, symbol: str, timeframe, start: datetime, end: datetime):
        key = self._tf_key(timeframe)
        df = self.df_by_tf[key]
        m = df[(df["time"] >= pd.Timestamp(start)) & (df["time"] <= pd.Timestamp(end))]
        return m.to_records(index=False)

def _load_cfg(cfg_path="config/config.yaml") -> Dict[str, Any]:
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _to_df(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    if "time" in df:
        df["time"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
    return df

def _metrics(pnl_list: List[float]) -> Dict[str, float]:
    if len(pnl_list) == 0:
        return dict(pnl=0.0, sharpe=0.0, pf=0.0, max_dd=0.0, winrate=0.0)
    s = pd.Series(pnl_list, dtype="float64")
    pnl = float(s.sum())
    sharpe = float((s.mean() / s.std()) if s.std() not in (0, np.nan) else 0.0)
    gains = s[s > 0].sum()
    losses = -s[s < 0].sum()
    pf = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
    equity = s.cumsum()
    peak = equity.cummax()
    max_dd = float((peak - equity).max() if len(equity) else 0.0)
    winrate = float((s > 0).mean()) if len(s) else 0.0
    return dict(pnl=pnl, sharpe=sharpe, pf=pf, max_dd=max_dd, winrate=winrate)

def _agent_section_name(agent_class_name: str) -> str:
    base = agent_class_name.replace("Agent", "")
    return base[:1].lower() + base[1:]

def _point_value(symbol: str, cfg, mt5c: MT5Client) -> float:
    info = mt5.symbol_info(symbol)
    if info and getattr(info, "trade_tick_size", 0) and getattr(info, "trade_tick_value", 0):
        return info.trade_tick_value / info.trade_tick_size
    # fallback YAML
    return float((cfg.get("broker_costs", {}) or {}).get("point_value_per_lot", 1.0))

def run_backtest_for_agent(
    agent_module: str,
    agent_class_name: str,
    cfg_path: str = "config/config.yaml",
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    csv_out: Optional[str] = None,
) -> BTResult:
    cfg = _load_cfg(cfg_path)
    symbol = symbol or cfg.get("symbol", "BTCUSD")

    costs = (cfg.get("broker_costs", {}) or {})
    commission_per_lot = float(costs.get("commission_per_lot", 0.0))
    spread_points = float(costs.get("spread_points", 0.0))
    slip_in = float(costs.get("slippage_points_entry", 0.0))
    slip_out = float(costs.get("slippage_points_exit", 0.0))

    sec = _agent_section_name(agent_class_name)
    agent_params = (cfg.get(sec, {}) or {}).get("params", {})
    tf = timeframe or agent_params.get("timeframe") or (cfg.get("timeframes", {}) or {}).get(sec, "H1")

    mt5c = MT5Client(cfg_path)
    if start is None or end is None:
        end = pd.Timestamp.utcnow()
        start = end - pd.Timedelta(days=365)
    raw = mt5c.copy_rates_range(symbol, tf, start, end)
    if raw is None or len(raw) == 0:
        return BTResult([], 0, 0.0, 0.0, 0.0, 0.0, 0.0, None)
    df_tf = _to_df(raw).reset_index(drop=True)
    df_tf["atr_bt"] = compute_atr(df_tf, period=int(agent_params.get("atr_period", 14))).fillna(method="bfill")

    fake = FakeMT5Client({tf: df_tf})

    mod = importlib.import_module(agent_module)
    cls = getattr(mod, agent_class_name)
    try:
        agent = cls(cfg=cfg, params=agent_params)
    except TypeError:
        agent = cls(cfg=cfg)
    if hasattr(agent, "mt5_client"):
        agent.mt5_client = fake

    # point value pour convertir points → devise par 1 lot
    pv = _point_value(symbol, cfg, mt5c)

    trades, records = [], []
    in_trade = False
    side = None
    entry = None
    sl = None
    tp = None

    for i in range(len(df_tf)):
        fake.set_pos(i)
        bar = df_tf.iloc[i]
        high = float(bar["high"]); low = float(bar["low"]); close = float(bar["close"])
        ts = pd.to_datetime(bar["time"])

        sig = None
        try:
            sig = agent.generate_signal()
        except Exception:
            sig = None

        if not in_trade and isinstance(sig, dict) and sig.get("signal") in ("LONG", "SHORT"):
            _sl = sig.get("sl"); _tp = sig.get("tp")
            if (_sl is None or _tp is None) and not np.isnan(bar.get("atr_bt", np.nan)):
                atr = float(bar["atr_bt"])
                tp_mult = float(agent_params.get("tp_mult", 2.0))
                sl_mult = float(agent_params.get("sl_mult", 1.5))
                if sig["signal"] == "LONG":
                    _sl = close - sl_mult * atr
                    _tp = close + tp_mult * atr
                else:
                    _sl = close + sl_mult * atr
                    _tp = close - tp_mult * atr

            if _sl is not None and _tp is not None:
                in_trade = True
                side = sig["signal"]
                # Entrée au marché avec slippage + demi-spread
                spread_half = spread_points / 2.0
                entry = close + (slip_in + spread_half) * (1 if side == "LONG" else -1)
                sl = float(_sl)
                tp = float(_tp)
                continue

        if in_trade:
            # sorties avec slippage + demi-spread dans le sens de la sortie
            spread_half = spread_points / 2.0
            if side == "LONG":
                if high >= tp:
                    exit_px = tp - (slip_out + spread_half)  # vender → pénalisé
                    pnl_points = (exit_px - entry)
                    pnl_value = pnl_points * pv
                    pnl_value -= commission_per_lot  # aller/retour (simple)
                    trades.append(pnl_value)
                    records.append(dict(time=ts, side=side, entry=entry, exit=exit_px, pnl=pnl_value))
                    in_trade = False
                elif low <= sl:
                    exit_px = sl - (slip_out + spread_half)
                    pnl_points = (exit_px - entry)
                    pnl_value = pnl_points * pv
                    pnl_value -= commission_per_lot
                    trades.append(pnl_value)
                    records.append(dict(time=ts, side=side, entry=entry, exit=exit_px, pnl=pnl_value))
                    in_trade = False
            else:  # SHORT
                if low <= tp:
                    exit_px = tp + (slip_out + spread_half)  # rachat → pénalisé
                    pnl_points = (entry - exit_px)
                    pnl_value = pnl_points * pv
                    pnl_value -= commission_per_lot
                    trades.append(pnl_value)
                    records.append(dict(time=ts, side=side, entry=entry, exit=exit_px, pnl=pnl_value))
                    in_trade = False
                elif high >= sl:
                    exit_px = sl + (slip_out + spread_half)
                    pnl_points = (entry - exit_px)
                    pnl_value = pnl_points * pv
                    pnl_value -= commission_per_lot
                    trades.append(pnl_value)
                    records.append(dict(time=ts, side=side, entry=entry, exit=exit_px, pnl=pnl_value))
                    in_trade = False

    if in_trade:
        last = float(df_tf["close"].iloc[-1])
        spread_half = spread_points / 2.0
        exit_px = last - (slip_out + spread_half) if side == "LONG" else last + (slip_out + spread_half)
        pnl_points = (exit_px - entry) if side == "LONG" else (entry - exit_px)
        pnl_value = pnl_points * pv - commission_per_lot
        trades.append(pnl_value)
        records.append(dict(time=df_tf["time"].iloc[-1], side=side, entry=entry, exit=exit_px, pnl=pnl_value))

    m = _metrics(trades)
    csv_path = None
    if records and csv_out:
        out_df = pd.DataFrame(records)
        out_df.to_csv(csv_out, index=False)
        csv_path = csv_out

    return BTResult(
        trades=trades,
        nb_trades=len(trades),
        pnl=m["pnl"],
        sharpe=m["sharpe"],
        profit_factor=m["pf"],
        max_dd=m["max_dd"],
        winrate=m["winrate"],
        csv_path=csv_path,
    )
# --- Compat adapter: expose AgentBacktester whatever the internal class is ---
try:
    AgentBacktester  # existe déjà ? alors ne rien faire
except NameError:
    # Si votre fichier définit une autre classe, par ex. RealisticBacktester/Backtester/etc.,
    # créez un alias ici. Exemple 1: si vous avez RealisticBacktester :
    try:
        AgentBacktester = RealisticBacktester  # type: ignore # noqa
    except NameError:
        # Exemple 2: s'il n'y a qu'un Backtester "simple", on l'aliasse temporairement.
        try:
            from backtest.backtest import Backtester as AgentBacktester  # noqa
        except Exception:
            # Dernier recours: petit stub pour ne pas casser les imports (à remplacer par votre moteur réel)
            from dataclasses import dataclass

            @dataclass
            class BTResult:
                cagr: float = 0.0
                max_drawdown: float = 0.0
                sharpe: float = 0.0
                trades: int = 0
                net_return: float = 0.0

            class AgentBacktester:  # type: ignore
                def __init__(self, *args, **kwargs):
                    pass
                def run(self) -> "BTResult":
                    return BTResult()