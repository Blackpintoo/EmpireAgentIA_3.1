# scheduler_empire.py - clean demo scheduler (no demo_tick)
import os, sys, time, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
PY = sys.executable


def job_backtest_daily(loc=None):
    # TODO: appelle ton backtest reel si disponible
    print("[scheduler] backtest quotidien (placeholder)")

    # Auto-tune ~19:05 local time
    if loc is None:
        loc = time.localtime()
    if loc.tm_hour == 19 and loc.tm_min == 5:  # type: ignore
        try:
            subprocess.run([PY, str(ROOT / "scripts" / "auto_tune_risk.py")], check=False)
        except Exception as e:
            print(f"[scheduler] auto_tune error: {e}")


def job_scan_tick():
    """
    Appelle un runner d'agents si present.
    On cherche 'scripts/run_agents.py' et on l'execute s'il existe.
    """
    target = ROOT / "scripts" / "run_agents.py"
    if target.exists():
        try:
            subprocess.run([PY, str(target)], check=False)
        except Exception as e:
            print(f"[scheduler] run_agents.py error: {e}")


def main():
    print("Scheduler lance : backtest quotidien a 20h00 + scan_tick/60s (Europe/Zurich).")
    last_scan = 0
    last_backtest_day = None

    while True:
        try:
            now = time.time()
            # Tick scan chaque 60s
            if now - last_scan >= 60:
                job_scan_tick()
                last_scan = now

            # Backtest quotidien a 20:00 (approx locale)
            loc = time.localtime()
            key = (loc.tm_year, loc.tm_yday)
            if loc.tm_hour == 20 and loc.tm_min == 0:
                if last_backtest_day != key:
                    job_backtest_daily(loc=loc)
                    last_backtest_day = key

            time.sleep(1)
        except KeyboardInterrupt:
            print("\n[scheduler] arrete par l'utilisateur")
            break
        except Exception as e:
            print(f"[scheduler] loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
