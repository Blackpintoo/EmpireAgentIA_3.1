import yaml
from datetime import datetime
from agents.scalping import ScalpingAgent
from agents.swing import SwingAgent
from agents.technical import TechnicalAgent
from agents.sentiment import SentimentAgent
from agents.news import NewsAgent
from agents.fundamental import FundamentalAgent
from utils.mt5_client import MT5Client
from utils.telegram_client import send_telegram_message
from backtest import optimize_agent   # ← Doit accepter tous ces agents

CONFIG_PATH = "config/config.yaml"
SYMBOL = "BTCUSD"
TIMEFRAME = MT5Client.TIMEFRAME_H1  # Pour scalping/swing/technical – adapte selon l’agent
START = datetime(2025, 7, 1)
END = datetime(2025, 7, 31)
CHAT_ID = "5277012507"
TOKEN = "7965345416:AAFCczT8l8OJLPf5zjTv5otReut3Khu4SXc"

# ---------------- Grilles de paramètres par agent ----------------
param_grid_scalp = {
    "rsi_period": [7, 10, 14],
    "ema_period": [21, 34],
    "atr_period": [14],
    "rsi_overbought": [70],
    "rsi_oversold": [30],
    "tp_mult": [1.5, 2.0],
    "sl_mult": [1.0, 1.5]
}
param_grid_swing = {
    "ema_period": [30, 50, 100],
    "rsi_period": [10, 14],
    "trend_rsi_long": [50, 55, 60],
    "trend_rsi_short": [40, 45, 50],
    "range_rsi_long": [25, 30, 35],
    "range_rsi_short": [65, 70, 75],
    "trend_tp_mult": [3.0, 4.0],
    "trend_sl_mult": [1.5, 2.0],
    "range_tp_mult": [1.5, 2.0],
    "range_sl_mult": [1.0, 1.5]
}
param_grid_tech = {
    "ema_period": [21, 50],
    "rsi_period": [10, 14],
    "macd_fast": [8, 12],
    "macd_slow": [21, 26],
    "macd_signal": [6, 9],
    "obv_window": [15, 20, 30],
    "atr_period": [10, 14],
    "tp_mult": [2.0, 2.5],
    "sl_mult": [1.5, 2.0],
    "votes_required": [3, 4],
    "rsi_overbought": [65, 70],
    "rsi_oversold": [30, 35]
}
param_grid_sentiment = {
    "fg_weight": [0.4, 0.5, 0.6],
    "twitter_weight": [0.2, 0.3, 0.4],
    "google_weight": [0.1, 0.2, 0.3],
    "neutral_fg": [50, 55],
    "upper_threshold": [0.3, 0.4, 0.5],
    "lower_threshold": [-0.5, -0.4, -0.3],
}
param_grid_news = {
    "keyword_weight": [1.0, 1.5, 2.0],
    "sentiment_threshold": [0.10, 0.15, 0.20],
    "signal_threshold": [1, 2, 3]
}
param_grid_fundamental = {
    "wait_minutes": [10, 15, 20],
    "only_high_impact": [True, False],
}

if __name__ == '__main__':
    # 1. Charger config YAML existant
    with open(CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)

    # 2. Lancer optimisation pour chaque agent
    best_params = {}
    results_summary = "📊 *Optimisation Multi-Agent Résumé*\n\n"

    # ScalpingAgent
    best_params_scalp, res_scalp = optimize_agent(
        ScalpingAgent, cfg, param_grid_scalp,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"🦾 ScalpingAgent : {best_params_scalp}\nRésultat : {res_scalp}\n\n"
    best_params["scalping_agent"] = best_params_scalp

    # SwingAgent
    best_params_swing, res_swing = optimize_agent(
        SwingAgent, cfg, param_grid_swing,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"🌊 SwingAgent : {best_params_swing}\nRésultat : {res_swing}\n\n"
    best_params["swing_agent"] = best_params_swing

    # TechnicalAgent
    best_params_tech, res_tech = optimize_agent(
        TechnicalAgent, cfg, param_grid_tech,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"📊 TechnicalAgent : {best_params_tech}\nRésultat : {res_tech}\n\n"
    best_params["technical_agent"] = best_params_tech

    # SentimentAgent
    best_params_sentiment, res_sentiment = optimize_agent(
        SentimentAgent, cfg, param_grid_sentiment,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"🧠 SentimentAgent : {best_params_sentiment}\nRésultat : {res_sentiment}\n\n"
    best_params["sentiment_agent"] = best_params_sentiment

    # NewsAgent
    best_params_news, res_news = optimize_agent(
        NewsAgent, cfg, param_grid_news,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"📰 NewsAgent : {best_params_news}\nRésultat : {res_news}\n\n"
    best_params["news_agent"] = best_params_news

    # FundamentalAgent
    best_params_fundamental, res_fundamental = optimize_agent(
        FundamentalAgent, cfg, param_grid_fundamental,
        SYMBOL, TIMEFRAME, START, END,
        send_telegram_message, CHAT_ID, TOKEN
    )
    results_summary += f"⚖️ FundamentalAgent : {best_params_fundamental}\nRésultat : {res_fundamental}\n\n"
    best_params["fundamental_agent"] = best_params_fundamental

    # 3. Update config.yaml avec tous les best_params
    for agent_key, params in best_params.items():
        if agent_key not in cfg:
            cfg[agent_key] = {}
        cfg[agent_key]["params"] = params

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print("✅ config.yaml mis à jour avec les meilleurs paramètres pour tous les agents !")

    # 4. Envoi résumé complet sur Telegram
    send_telegram_message(text=results_summary, kind="status", cfg={"chat_id": CHAT_ID, "token": TOKEN})

