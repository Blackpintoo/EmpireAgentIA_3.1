import pandas as pd
from datetime import datetime
from utils.mt5_client import MT5Client
from utils.indicators import compute_rsi, compute_ema, compute_atr, compute_macd, compute_obv

class Backtester:
    def __init__(self, agent_class, cfg, params=None):
        self.agent_class = agent_class
        self.cfg = cfg or {}
        self.params = params or {}

    def run(self, symbol, timeframe, start, end):
        mt5 = MT5Client()
        rates = mt5.copy_rates_range(symbol, timeframe, start, end)
        if rates is None or len(rates) == 0:
            return {'pnl': 0.0, 'sharpe': 0.0, 'drawdown': 0.0, 'nb_trades': 0, 'trades': []}
        df = pd.DataFrame(rates)
        if 'time' in df:
            df['time'] = pd.to_datetime(df['time'], unit='s')

        agent = self.agent_class(symbol=symbol, cfg=self.cfg, params=self.params)

        # Auto-compute indicators if the agent expects them by param keys
        if 'ema_period' in agent.params:
            df['ema'] = compute_ema(df['close'], agent.params['ema_period'])
        if 'rsi_period' in agent.params:
            df['rsi'] = compute_rsi(df['close'], agent.params['rsi_period'])
        if 'atr_period' in agent.params:
            df['atr'] = compute_atr(df, agent.params['atr_period'])
        if {'macd_fast','macd_slow','macd_signal'}.issubset(agent.params.keys()):
            macd_line, macd_signal, hist = compute_macd(
                df['close'], agent.params['macd_fast'], agent.params['macd_slow'], agent.params['macd_signal']
            )
            df['macd'] = macd_line
            df['macd_signal'] = macd_signal
            df['macd_hist'] = hist
        if 'obv_window' in agent.params:
            df['obv'] = compute_obv(df)

        trades = []
        in_trade = False
        entry_price = None
        direction = None
        entry_atr = None

        for bar in df.itertuples():
            signal_dict = agent.generate_signal(bar)
            sig = signal_dict.get('signal') if isinstance(signal_dict, dict) else signal_dict

            if not in_trade and sig in ('LONG', 'SHORT'):
                in_trade = True
                entry_price = getattr(bar, 'close', None)
                direction = sig
                entry_atr = getattr(bar, 'atr', None)
                if entry_price is None:
                    in_trade = False
                    direction = None
                    continue
            elif in_trade:
                high = getattr(bar, 'high', None)
                low = getattr(bar, 'low', None)
                close = getattr(bar, 'close', None)
                atr_val = entry_atr or 0.0
                tp_mult = float(agent.params.get('tp_mult', 2.0))
                sl_mult = float(agent.params.get('sl_mult', 1.5))

                if direction == 'LONG' and high is not None and low is not None:
                    if high >= entry_price + atr_val * tp_mult:
                        trades.append(high - entry_price)
                        in_trade = False
                    elif low <= entry_price - atr_val * sl_mult:
                        trades.append(low - entry_price)
                        in_trade = False
                elif direction == 'SHORT' and high is not None and low is not None:
                    if low <= entry_price - atr_val * tp_mult:
                        trades.append(entry_price - low)
                        in_trade = False
                    elif high >= entry_price + atr_val * sl_mult:
                        trades.append(entry_price - high)
                        in_trade = False

        if in_trade and entry_price is not None:
            last_close = df['close'].iloc[-1]
            if direction == 'LONG':
                trades.append(last_close - entry_price)
            else:
                trades.append(entry_price - last_close)

        pnl = pd.Series(trades, dtype='float64')
        sharpe = float(pnl.mean() / pnl.std()) if len(pnl) > 1 and pnl.std() != 0 else 0.0
        drawdown = self._max_drawdown(pnl) if len(pnl) else 0.0
        return {'pnl': float(pnl.sum()), 'sharpe': sharpe, 'drawdown': float(drawdown), 'nb_trades': int(len(trades)), 'trades': trades}

    def _max_drawdown(self, pnl: pd.Series):
        equity = pnl.cumsum()
        peak = equity.cummax()
        dd = (peak - equity)
        return dd.max() if len(dd) else 0.0

def run_backtest_agent(agent_class, cfg, symbol, timeframe, start, end, params=None):
    return Backtester(agent_class, cfg, params).run(symbol, timeframe, start, end)
