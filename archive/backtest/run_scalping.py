# backtest/run_scalping.py
from datetime import datetime
from backtest.agent_backtest import run_backtest_for_agent

if __name__ == "__main__":
    res = run_backtest_for_agent(
        agent_module="agents.scalping",
        agent_class_name="ScalpingAgent",
        cfg_path="config/config.yaml",
        symbol=None,              # prend le symbol du YAML si None
        timeframe=None,           # prend le TF de l'agent/YAML si None
        start=datetime(2024,1,1),
        end=datetime(2024,12,31),
        csv_out="backtest_scalping_trades.csv",
    )
    print(f"Trades: {res.nb_trades} | PnL={res.pnl:.2f} | Sharpe={res.sharpe:.2f} | PF={res.profit_factor:.2f} | MaxDD={res.max_dd:.2f} | Winrate={res.winrate:.2%}")
    if res.csv_path:
        print(f"CSV: {res.csv_path}")
