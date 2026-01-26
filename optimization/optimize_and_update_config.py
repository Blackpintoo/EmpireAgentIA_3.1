from datetime import datetime
from agents.scalping import ScalpingAgent
from utils.mt5_client import MT5Client
from utils.telegram_client import send_telegram_message
from backtest import optimize_agent
import yaml

CONFIG_PATH = "config/config.yaml"
SYMBOL = "BTCUSD"
TIMEFRAME = MT5Client.TIMEFRAME_M1
START = datetime(2025, 7, 1)
END = datetime(2025, 7, 31)
CHAT_ID = "5277012507"
TOKEN = "7965345416:AAFCczT8l8OJLPf5zjTv5otReut3Khu4SXc"

param_grid = {
    "rsi_period": [7, 10, 14],
    "ema_period": [21, 34],
    "atr_period": [14],
    "rsi_overbought": [70],
    "rsi_oversold": [30],
    "tp_mult": [1.5, 2.0],
    "sl_mult": [1.0, 1.5]
}

if __name__ == '__main__':
    # 1. Charger config YAML
    with open(CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)

    # 2. Optimiser et trouver les meilleurs paramètres
    best_params, best_result = optimize_agent(
        ScalpingAgent, cfg, param_grid,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message,
        CHAT_ID, TOKEN
    )

    print("Meilleurs paramètres :", best_params)

    # 3. Mettre à jour la config YAML
    # Chemin recommandé : cfg["scalping_agent"]["params"] (adapte selon ta structure)
    if "scalping_agent" not in cfg:
        cfg["scalping_agent"] = {}
    cfg["scalping_agent"]["params"] = best_params

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print("✅ config.yaml mis à jour avec les meilleurs paramètres !")
