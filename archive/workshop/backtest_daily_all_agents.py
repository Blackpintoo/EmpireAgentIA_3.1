import yaml
from datetime import datetime, timedelta
import pytz
import json
from backtest.agent_backtest import run_backtest_for_agent
from agents.scalping import ScalpingAgent
from agents.swing import SwingAgent
from agents.technical import TechnicalAgent
from agents.news import NewsAgent
from agents.fundamental import FundamentalAgent
from agents.sentiment import SentimentAgent
from utils.telegram_client import send_telegram_message

# Charge la config YAML
with open("config/config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

symbol = cfg.get("symbol", "BTCUSD")
tz = pytz.timezone("Europe/Zurich")
today = datetime.now(tz).date()
start = datetime(today.year, today.month, today.day, tzinfo=tz) - timedelta(days=30)
end = datetime.now(tz)

# Liste des agents à backtester
AGENTS = {
    "scalping_agent": (ScalpingAgent, cfg.get("scalping", {})),
    "swing_agent": (SwingAgent, cfg.get("swing", {})),
    "technical_agent": (TechnicalAgent, cfg.get("technical", {})),
    "news_agent": (NewsAgent, cfg.get("news", {})),
    "fundamental_agent": (FundamentalAgent, cfg.get("fundamental", {})),
    "sentiment_agent": (SentimentAgent, cfg.get("sentiment", {})),
}

results_all = {}
for agent_key, (cls, agent_cfg) in AGENTS.items():
    timeframe = agent_cfg.get("timeframe", cfg.get("timeframes", {}).get(agent_key.split("_")[0], "M1"))
    try:
        result = run_backtest_for_agent(
            agent_module=f"agents.{agent_key.split('_')[0]}",
            agent_class_name=cls.__name__,
            cfg_path="config/config.yaml",
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            csv_out=f"backtest_{agent_key}_trades.csv",
        )
        results_all[agent_key] = result.__dict__ if hasattr(result, "__dict__") else result
    except Exception as e:
        results_all[agent_key] = {"error": str(e)}
        print(f"❌ Erreur backtest {agent_key}: {e}")

# Sauvegarde JSON
date_str = start.strftime("%Y-%m-%d")
with open(f"backtest_results_{symbol}_{date_str}.json", "w", encoding="utf-8") as f:
    json.dump(results_all, f, indent=2, default=str, ensure_ascii=False)

# Résumé pour Telegram
msg = [f"📊 Backtest EmpireAgentIA du {date_str} terminé."]
for agent_key, res in results_all.items():
    name = agent_key.replace("_agent", "").capitalize()
    if isinstance(res, dict) and "pnl" in res:
        pnl = float(res.get("pnl", 0))
        sharpe = float(res.get("sharpe", 0))
        trades = int(res.get("nb_trades", res.get("trades", 0) if isinstance(res.get("trades"), int) else 0))
        msg.append(f"• {name} — PnL={pnl:.2f}, Sharpe={sharpe:.2f}, Trades={trades}")
    else:
        msg.append(f"• {name}: Erreur : {res.get('error','?') if isinstance(res, dict) else res}")
send_telegram_message(text="\n".join(msg), kind="status")
print("✅ Notification Telegram envoyée !")
