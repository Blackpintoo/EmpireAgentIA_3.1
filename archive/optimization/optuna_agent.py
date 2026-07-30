# optimization/optuna_agent.py
import optuna
import yaml
from datetime import datetime
from pathlib import Path
from backtest.agent_backtest import run_backtest_for_agent

# Map simple module/class par agent
AGENT_MAP = {
    "scalping": ("agents.scalping", "ScalpingAgent"),
    "swing": ("agents.swing", "SwingAgent"),
    "technical": ("agents.technical", "TechnicalAgent"),
}

def load_cfg(path="config/config.yaml"):
    return yaml.safe_load(open(path, encoding="utf-8")) or {}

def save_cfg(cfg, path="config/config.yaml"):
    yaml.safe_dump(cfg, open(path, "w", encoding="utf-8"), sort_keys=False, allow_unicode=True)

def objective(trial, agent_key: str, cfg_path: str, start: datetime, end: datetime):
    cfg = load_cfg(cfg_path)
    params = (cfg.get(agent_key, {}) or {}).get("params", {})

    # Espace de recherche — adapte selon l’agent
    if agent_key == "scalping":
        params["rsi_period"] = trial.suggest_int("rsi_period", 5, 14)
        params["ema_period"] = trial.suggest_int("ema_period", 10, 55)
        params["tp_mult"] = trial.suggest_float("tp_mult", 1.2, 3.5, step=0.1)
        params["sl_mult"] = trial.suggest_float("sl_mult", 1.0, 2.5, step=0.1)
        params["rsi_overbought"] = trial.suggest_int("rsi_overbought", 60, 75)
        params["rsi_oversold"] = trial.suggest_int("rsi_oversold", 25, 45)
    elif agent_key == "swing":
        params["ema_period"] = trial.suggest_int("ema_period", 20, 100)
        params["rsi_period"] = trial.suggest_int("rsi_period", 7, 21)
        params["trend_tp_mult"] = trial.suggest_float("trend_tp_mult", 2.0, 6.0, step=0.2)
        params["trend_sl_mult"] = trial.suggest_float("trend_sl_mult", 1.0, 3.0, step=0.1)
    elif agent_key == "technical":
        params["ema_period"] = trial.suggest_int("ema_period", 20, 100)
        params["rsi_period"] = trial.suggest_int("rsi_period", 7, 21)
        params["tp_mult"] = trial.suggest_float("tp_mult", 1.5, 3.5, step=0.1)
        params["sl_mult"] = trial.suggest_float("sl_mult", 1.0, 3.0, step=0.1)

    # Sauvegarde temporaire (pour que run_backtest lise ces params)
    cfg.setdefault(agent_key, {})["params"] = params
    tmp_path = "_tmp_config.yaml"
    save_cfg(cfg, tmp_path)

    module, cls = AGENT_MAP[agent_key]
    res = run_backtest_for_agent(
        agent_module=module,
        agent_class_name=cls,
        cfg_path=tmp_path,
        start=start,
        end=end,
        csv_out=None
    )

    # Score multi-critères : Sharpe prioritaire + petit bonus PnL – pénalité DD
    score = (res.sharpe or 0.0) * 2.0 + (res.pnl or 0.0) * 0.0001 - (res.max_dd or 0.0) * 0.0001
    return score

def optimize_agent(agent_key: str, cfg_path="config/config.yaml", n_trials=40,
                   start=datetime(2024,1,1), end=datetime(2024,12,31)):
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda t: objective(t, agent_key, cfg_path, start, end), n_trials=n_trials)

    best_params = study.best_params
    cfg = load_cfg(cfg_path)
    cfg.setdefault(agent_key, {}).setdefault("params", {}).update(best_params)
    save_cfg(cfg, cfg_path)

    print(f"[Optuna] {agent_key} — best score={study.best_value:.4f}")
    print("Best params:", best_params)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--agent", choices=["scalping","swing","technical"], required=True)
    p.add_argument("--trials", type=int, default=40)
    p.add_argument("--start", type=str, default="2024-01-01")
    p.add_argument("--end", type=str, default="2024-12-31")
    args = p.parse_args()

    s = datetime.fromisoformat(args.start)
    e = datetime.fromisoformat(args.end)
    optimize_agent(args.agent, n_trials=args.trials, start=s, end=e)
