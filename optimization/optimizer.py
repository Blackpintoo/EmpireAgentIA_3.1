# optimization/optimizer.py
from pathlib import Path
import yaml
import optuna
from datetime import datetime, timedelta

from backtest.agent_backtest import AgentBacktester  # <-- moteur avec spread/slippage/commission
from utils.config import load_config, save_config  # vos helpers YAML
try:
    from utils.logger import get_logger
except Exception:
    # petit fallback si utils.logger n’existe pas
    import logging
    def get_logger(name):
        lg = logging.getLogger(name)
        if not lg.handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        return lg
log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.yaml"

def _date_range(months: int = 6):
    end = datetime.utcnow()
    start = end - timedelta(days=30*months)
    return start, end

def _suggest_params(trial: optuna.Trial, agent_key: str, defaults: dict):
    """
    Définir ici les hyperparamètres exposés par agent.
    On garde les valeurs par défaut comme bornes raisonnables.
    """
    p = {}
    if agent_key == "technical":
        p["ema_fast"] = trial.suggest_int("ema_fast", 8, 30, step=2)
        p["ema_slow"] = trial.suggest_int("ema_slow", 50, 200, step=10)
        p["rsi_period"] = trial.suggest_int("rsi_period", 7, 21)
        p["rsi_buy"] = trial.suggest_int("rsi_buy", 40, 55)
        p["rsi_sell"] = trial.suggest_int("rsi_sell", 45, 60)
    elif agent_key == "scalping":
        p["atr_period"] = trial.suggest_int("atr_period", 7, 21)
        p["atr_mult"] = trial.suggest_float("atr_mult", 0.8, 2.5)
        p["lookback"] = trial.suggest_int("lookback", 20, 120)
    elif agent_key == "swing":
        p["supertrend_period"] = trial.suggest_int("supertrend_period", 7, 20)
        p["supertrend_mult"] = trial.suggest_float("supertrend_mult", 1.5, 4.0)
        p["bos_lookback"] = trial.suggest_int("bos_lookback", 50, 250, step=10)
    elif agent_key == "structure":
        # PHASE 3: Paramètres Structure Agent (BOS/CHOCH patterns)
        p["lookback"] = trial.suggest_int("lookback", 100, 400, step=20)
        p["pivot_window"] = trial.suggest_int("pivot_window", 3, 10)
        p["atr_period"] = trial.suggest_int("atr_period", 10, 21)
        p["sl_mult"] = trial.suggest_float("sl_mult", 1.0, 2.5)
        p["tp_mult"] = trial.suggest_float("tp_mult", 1.5, 4.0)
        p["min_structure_strength"] = trial.suggest_float("min_structure_strength", 0.5, 0.9)
    elif agent_key == "smart_money":
        # PHASE 3: Paramètres Smart Money Agent (FVG, Order Blocks)
        p["lookback"] = trial.suggest_int("lookback", 200, 500, step=20)
        p["trend_lookback"] = trial.suggest_int("trend_lookback", 40, 120, step=10)
        p["eq_lookback"] = trial.suggest_int("eq_lookback", 8, 20)
        p["imbalance_lookback"] = trial.suggest_int("imbalance_lookback", 20, 60, step=5)
        p["order_block_lookback"] = trial.suggest_int("order_block_lookback", 30, 80, step=5)
        p["atr_period"] = trial.suggest_int("atr_period", 10, 21)
        p["sl_mult"] = trial.suggest_float("sl_mult", 1.0, 2.5)
        p["tp_mult"] = trial.suggest_float("tp_mult", 1.8, 3.5)
        p["slope_threshold"] = trial.suggest_float("slope_threshold", 5e-5, 5e-4, log=True)
    else:
        # pour news/fundamental/sentiment, on ne fait que des poids/biais
        p["bias_weight"] = trial.suggest_float("bias_weight", 0.2, 1.5)
    # fallback vers defaults pour les clés non optimisées
    for k, v in defaults.items():
        p.setdefault(k, v)
    return p

def optimize_agent(agent_key: str, symbol: str, months: int = 6, n_trials: int = 30) -> dict:
    cfg = load_config(CONFIG_PATH)
    agent_cfg = cfg["agents"].get(agent_key, {})
    risk_cfg = cfg.get("risk", {})
    bt_cfg = cfg.get("backtest", {})
    start, end = _date_range(months)

    def objective(trial: optuna.Trial):
        params = _suggest_params(trial, agent_key, agent_cfg.get("params", {}))

        bt = AgentBacktester(
            symbol=symbol,
            agent_key=agent_key,
            agent_params=params,
            start=start,
            end=end,
            timeframe=bt_cfg.get("timeframe", "H1"),
            spread=bt_cfg.get("spread_points", 20),
            slippage=bt_cfg.get("slippage_points", 10),
            commission_per_lot=bt_cfg.get("commission_per_lot", 7.0),
            risk_config=risk_cfg,
        )
        res = bt.run()
        # Métrique robuste : rendement annualisé pénalisé par drawdown & coût
        score = (res.cagr or 0) - 0.3*(res.max_drawdown or 0) + 0.0005*(res.trades or 0)
        # on veut maximiser
        trial.set_user_attr("result", {
            "cagr": res.cagr, "mdd": res.max_drawdown, "sharpe": res.sharpe, "trades": res.trades, "net": res.net_return
        })
        return score

    study = optuna.create_study(direction="maximize", study_name=f"{agent_key}_{symbol}")
    study.optimize(objective, n_trials=n_trials, n_jobs=1)

    best_params = _suggest_params(study.best_trial, agent_key, agent_cfg.get("params", {}))
    # Écrit dans le YAML puis sauvegarde
    cfg["agents"].setdefault(agent_key, {}).setdefault("params", {}).update(best_params)
    save_config(cfg, CONFIG_PATH)
    log.info(f"[{agent_key}] Best score={study.best_value:.4f} | params={best_params}")
    return best_params
