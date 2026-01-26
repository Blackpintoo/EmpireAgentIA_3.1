from datetime import datetime
from backtest.agent_backtest import run_backtest_for_agent

if __name__ == "__main__":
    res = run_backtest_for_agent(
        agent_module="agents.technical",
        agent_class_name="TechnicalAgent",
        start=datetime(2024,1,1),
        end=datetime(2024,12,31),
        csv_out="backtest_technical_trades.csv",
    )
    print(res)
