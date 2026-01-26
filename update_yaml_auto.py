import yaml
import json
from utils.telegram_client import send_telegram_message

YAML_FILE = "config.yaml"
RESULTS_FILE = "backtest_results_BTCUSD_2025-08-08.json"  # adapte dynamiquement si besoin

def rule_update_params(agent, params, results):
    # Exemple : si Sharpe < 1, augmente sl_mult de 0.2
    sharpe = results.get("sharpe", 1)
    if sharpe < 1:
        if "sl_mult" in params:
            old = params["sl_mult"]
            params["sl_mult"] = round(params["sl_mult"] + 0.2, 2)
            print(f"{agent}: sl_mult up {old} → {params['sl_mult']}")
    # Ajoute d'autres règles ici (ajuste TP, RSI, etc. selon tes critères)
    # Si drawdown trop élevé, baisse position_size_pct dans cfg["risk"]
    return params

def main():
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    with open(RESULTS_FILE) as f:
        results_all = json.load(f)

    updated = False
    msg = "🔁 Adaptation automatique EmpireAgentIA\n"
    for agent_key, results in results_all.items():
        if "params" in cfg.get(agent_key, {}):
            old_params = dict(cfg[agent_key]["params"])
            new_params = rule_update_params(agent_key, old_params, results)
            if old_params != new_params:
                cfg[agent_key]["params"] = new_params
                updated = True
                msg += f"• {agent_key.replace('_agent','').capitalize()} : Params adaptés ({results.get('sharpe','?')})\n"

    if updated:
        with open("config/config.yaml") as f:
            yaml.safe_dump(cfg, f)
        send_telegram_message(text="ℹ️ Routine auto-adaptation : aucun paramètre modifié.", kind="status")

        print("✅ YAML updated")
    else:
        send_telegram_message("ℹ️ Routine auto-adaptation : aucun paramètre modifié.")
        print("Aucun paramètre à modifier.")

if __name__ == "__main__":
    main()
