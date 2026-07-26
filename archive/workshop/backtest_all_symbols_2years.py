"""
PHASE 3 - Backtest complet sur 2 ans pour les 16 symboles
Teste les 5 agents actifs sur chaque symbole et génère un rapport complet
"""
import yaml
import json
import pandas as pd
from datetime import datetime, timedelta
import pytz
from pathlib import Path
from backtest.agent_backtest import run_backtest_for_agent
from utils.telegram_client import send_telegram_message

# Configuration
CONFIG_PATH = "config/config.yaml"
with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

# Liste des 16 symboles (PHASE 2)
SYMBOLS = [
    # CRYPTOS (6)
    "BTCUSD", "ETHUSD", "BNBUSD", "LINKUSD", "ADAUSD", "SOLUSD",
    # FOREX (4)
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
    # MATIÈRES (3)
    "XAUUSD", "XAGUSD", "USOIL",
    # INDICES (3)
    "US30", "NAS100", "GER40"
]

# Agents actifs (PHASE 1)
AGENTS = [
    ("scalping", "ScalpingAgent"),
    ("swing", "SwingAgent"),
    ("technical", "TechnicalAgent"),
    ("structure", "StructureAgent"),
    ("smart_money", "SmartMoneyAgent"),
]

# Période de backtest : 2 ans
tz = pytz.timezone("Europe/Zurich")
end = datetime.now(tz)
start = end - timedelta(days=730)  # 2 ans

print("=" * 80)
print("🚀 PHASE 3 - BACKTEST COMPLET SUR 2 ANS")
print("=" * 80)
print(f"📅 Période : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
print(f"📊 Symboles : {len(SYMBOLS)} symboles")
print(f"🤖 Agents : {len(AGENTS)} agents actifs")
print(f"📈 Total tests : {len(SYMBOLS) * len(AGENTS)} backtests")
print("=" * 80)

# Résultats globaux
results_all = {}
summary_stats = {
    "total_tests": 0,
    "successful_tests": 0,
    "failed_tests": 0,
    "total_trades": 0,
    "total_pnl": 0.0,
    "avg_sharpe": 0.0,
    "avg_winrate": 0.0,
    "best_agent": None,
    "best_symbol": None,
    "best_pnl": float('-inf'),
}

# Boucle sur chaque symbole
for symbol in SYMBOLS:
    print(f"\n📊 Testing {symbol}...")
    results_all[symbol] = {}

    # Boucle sur chaque agent
    for agent_key, agent_class in AGENTS:
        summary_stats["total_tests"] += 1

        # Timeframe par agent
        timeframe = cfg.get(agent_key, {}).get("params", {}).get("timeframe", "H1")

        try:
            result = run_backtest_for_agent(
                agent_module=f"agents.{agent_key}",
                agent_class_name=agent_class,
                cfg_path=CONFIG_PATH,
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                csv_out=f"data/backtest_{symbol}_{agent_key}_2years.csv",
            )

            # Stockage des résultats
            results_all[symbol][agent_key] = {
                "nb_trades": result.nb_trades,
                "pnl": round(result.pnl, 2),
                "sharpe": round(result.sharpe, 3),
                "profit_factor": round(result.profit_factor, 2),
                "max_drawdown": round(result.max_dd, 2),
                "winrate": round(result.winrate * 100, 1),
                "timeframe": timeframe,
            }

            # Mise à jour des stats globales
            summary_stats["successful_tests"] += 1
            summary_stats["total_trades"] += result.nb_trades
            summary_stats["total_pnl"] += result.pnl
            summary_stats["avg_sharpe"] += result.sharpe
            summary_stats["avg_winrate"] += result.winrate

            # Meilleur agent/symbole
            if result.pnl > summary_stats["best_pnl"]:
                summary_stats["best_pnl"] = result.pnl
                summary_stats["best_agent"] = agent_key
                summary_stats["best_symbol"] = symbol

            print(f"  ✅ {agent_key:15} | Trades: {result.nb_trades:4} | PnL: {result.pnl:8.2f} | Sharpe: {result.sharpe:5.2f} | WR: {result.winrate*100:5.1f}%")

        except Exception as e:
            summary_stats["failed_tests"] += 1
            results_all[symbol][agent_key] = {"error": str(e)}
            print(f"  ❌ {agent_key:15} | Error: {str(e)[:50]}")

# Calcul des moyennes
if summary_stats["successful_tests"] > 0:
    summary_stats["avg_sharpe"] /= summary_stats["successful_tests"]
    summary_stats["avg_winrate"] /= summary_stats["successful_tests"]

# Sauvegarde JSON complète
output_file = f"data/backtest_all_symbols_2years_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
Path("data").mkdir(exist_ok=True)
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({
        "metadata": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "symbols": SYMBOLS,
            "agents": [a[0] for a in AGENTS],
        },
        "summary": summary_stats,
        "results": results_all,
    }, f, indent=2, default=str, ensure_ascii=False)

print("\n" + "=" * 80)
print("📊 RÉSUMÉ GLOBAL")
print("=" * 80)
print(f"✅ Tests réussis : {summary_stats['successful_tests']}/{summary_stats['total_tests']}")
print(f"❌ Tests échoués : {summary_stats['failed_tests']}")
print(f"📈 Total trades : {summary_stats['total_trades']}")
print(f"💰 PnL total : {summary_stats['total_pnl']:.2f}")
print(f"📊 Sharpe moyen : {summary_stats['avg_sharpe']:.3f}")
print(f"🎯 Winrate moyen : {summary_stats['avg_winrate']*100:.1f}%")
print(f"🏆 Meilleur combo : {summary_stats['best_symbol']} + {summary_stats['best_agent']} (PnL: {summary_stats['best_pnl']:.2f})")
print(f"💾 Résultats sauvegardés : {output_file}")
print("=" * 80)

# Notification Telegram
msg = [
    "📊 PHASE 3 - Backtest 2 ans terminé",
    f"✅ {summary_stats['successful_tests']}/{summary_stats['total_tests']} tests réussis",
    f"📈 {summary_stats['total_trades']} trades | PnL: {summary_stats['total_pnl']:.2f}",
    f"📊 Sharpe: {summary_stats['avg_sharpe']:.2f} | WR: {summary_stats['avg_winrate']*100:.1f}%",
    f"🏆 Best: {summary_stats['best_symbol']} + {summary_stats['best_agent']}",
]

try:
    send_telegram_message(text="\n".join(msg), kind="status")
    print("✅ Notification Telegram envoyée !")
except Exception as e:
    print(f"⚠️ Erreur notification Telegram : {e}")
