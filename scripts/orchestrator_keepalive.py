# scripts/orchestrator_keepalive.py
import time, logging, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("orchestrator_keepalive")
    try:
        from utils.health import start_health_server
        start_health_server(host="0.0.0.0", port=9108)
        log.info("[/healthz] ready on :9108")
    except Exception as e:
        log.warning("health server unavailable: %s", e)

    # Import “silencieux” de l’orchestrateur pour charger la config
    try:
        import orchestrator.orchestrator as _  # noqa: F401
        log.info("orchestrator module importé.")
    except Exception as e:
        log.warning("import orchestrator.orchestrator échoué: %s", e)

    log.info("orchestrator_keepalive lancé (Ctrl+C pour arrêter).")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Arrêt demandé par l’utilisateur.")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
