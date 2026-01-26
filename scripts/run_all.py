# scripts/run_all.py
import os, sys, subprocess, platform
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(ROOT, ".."))
PY = sys.executable  # utilise le python courant

def run(cmd, cwd=PROJ):
    print(f"\n> {cmd}")
    result = subprocess.run(cmd, cwd=cwd, shell=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

def backtest_agents():
    # Période par défaut (modifiable ici)
    start = "2024-01-01"
    end   = "2024-12-31"

    # 1) Backtests (agent par agent) -> CSV
    run(f'{PY} -m backtest.run_scalping')
    run(f'{PY} -m backtest.run_swing')
    run(f'{PY} -m backtest.run_technical')

def optuna_agents(trials=25):
    start = "2024-01-01"
    end   = "2024-12-31"

    # 2) Optuna (écrit les meilleurs params dans config.yaml)
    for agent in ("scalping", "swing", "technical"):
        run(f'{PY} -m optimization.optuna_agent --agent {agent} --trials {trials} --start {start} --end {end}')

def launch_dashboard():
    # 3) Streamlit (ouvre le dashboard)
    # Laisse l’appli tourner dans un autre process
    cmd = f'{PY} -m streamlit run dashboard/backtest_app.py'
    if platform.system().lower().startswith("win"):
        # nouvelle fenêtre
        subprocess.Popen(cmd, cwd=PROJ, shell=True)
    else:
        # lance en arrière-plan
        subprocess.Popen(cmd, cwd=PROJ, shell=True)

if __name__ == "__main__":
    print("=== Empire IA • Run All (backtests + optuna + dashboard) ===")
    backtest_agents()
    optuna_agents(trials=25)
    launch_dashboard()
    print("\n✅ Terminé. Le dashboard Streamlit va s’ouvrir. Si besoin :")
    print("   streamlit run dashboard/backtest_app.py")
