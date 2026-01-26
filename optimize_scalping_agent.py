from datetime import datetime
import yaml
from agents.scalping import ScalpingAgent
from utils.mt5_client import MT5Client
from utils.telegram_client import send_telegram_message
from optimization.optimizer import optimize_agent

if __name__ == '__main__':
    cfg = yaml.safe_load(open('config/config.yaml', encoding='utf-8'))

    SYMBOL = cfg.get('symbol', 'BTCUSD')
    TIMEFRAME = MT5Client.TIMEFRAME_M1
    START = datetime(2024, 1, 1)
    END = datetime(2024, 12, 31)
    CHAT_ID = str(cfg['telegram']['chat_id'])
    TOKEN = str(cfg['telegram']['token'])

    param_grid = {
        'rsi_period': [7, 9, 14],
        'ema_period': [21, 34],
        'atr_period': [14],
        'rsi_overbought': [65, 70],
        'rsi_oversold': [30, 35],
        'tp_mult': [1.5, 2.0],
        'sl_mult': [1.0, 1.5]
    }

    best_params, best_result = optimize_agent(
        ScalpingAgent, cfg, param_grid,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    print('Best parameters:', best_params)
    print('Best result:', best_result)
