from datetime import datetime
from backtest.agent_backtest import run_backtest_for_agent

if __name__ == "__main__":
    res = run_backtest_for_agent(
        agent_module="agents.swing",
        agent_class_name="SwingAgent",
        start=datetime(2024,1,1),
        end=datetime(2024,12,31),
        csv_out="backtest_swing_trades.csv",
    )
    print(res)
