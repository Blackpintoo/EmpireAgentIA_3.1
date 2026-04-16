# main.py (tout en haut)
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

# Charger .env AVANT tout import qui en dépend
from utils.config_loader import load_dotenv_env
load_dotenv_env(path=os.path.join(ROOT, ".env"), extra_paths=(), overwrite=False)

import yaml
import asyncio
from orchestrator.orchestrator import Orchestrator
from utils.telegram_client_async import AsyncTelegramClient
from utils.telegram_client import send_telegram_message
from utils.config import get_enabled_symbols, load_config
from utils.logger import logger

# =============================================================================
# AUDIT 2025-12-27: Import des nouveaux modules de monitoring
# =============================================================================
try:
    from utils.trade_outcome_tracker import start_outcome_tracking
    OUTCOME_TRACKER_AVAILABLE = True
except ImportError:
    start_outcome_tracking = None
    OUTCOME_TRACKER_AVAILABLE = False

try:
    from utils.loss_pattern_analyzer import get_loss_analyzer
    LOSS_ANALYZER_AVAILABLE = True
except ImportError:
    get_loss_analyzer = None
    LOSS_ANALYZER_AVAILABLE = False

if __name__ == "__main__":
    cfg = load_config()
    tg_token = cfg["telegram"]["token"]
    tg_chat_id = cfg["telegram"]["chat_id"]
    tg_client = AsyncTelegramClient(tg_token, tg_chat_id)

    # Récupérer tous les symboles activés
    try:
        enabled_symbols = get_enabled_symbols()
        logger.info(f"[MAIN] Symboles activés : {enabled_symbols} ({len(enabled_symbols)} symboles)")
    except Exception as e:
        logger.error(f"[MAIN] Erreur chargement symboles : {e}")
        enabled_symbols = ["BTCUSD"]  # Fallback

    # Message de démarrage avec nombre de symboles
    send_telegram_message(
        text=f"🚀 **EmpireAgentIA v3 - DÉMARRAGE MODE RÉEL**\n\n"
             f"Symboles actifs : {len(enabled_symbols)}\n"
             f"• CRYPTOS : BTCUSD, ETHUSD, BNBUSD, LTCUSD, ADAUSD, SOLUSD\n"
             f"• FOREX : EURUSD, GBPUSD, USDJPY, AUDUSD\n"
             f"• INDICES : DJ30, NAS100, GER40\n"
             f"• COMMODITIES : XAUUSD, XAGUSD, CL-OIL\n\n"
             f"✅ Sessions de marché actives\n"
             f"✅ Risk management par type d'actif\n"
             f"✅ Auto-optimization hebdomadaire",
        kind="startup"
    )

    # Créer un orchestrateur par symbole
    orchestrators = []
    for sym in enabled_symbols:
        try:
            orch = Orchestrator(symbol=sym, telegram_client=tg_client)
            orchestrators.append(orch)
            logger.info(f"[MAIN] Orchestrateur créé pour {sym}")
        except Exception as e:
            logger.error(f"[MAIN] Erreur création orchestrateur {sym} : {e}")

    logger.info(f"[MAIN] {len(orchestrators)} orchestrateurs créés et prêts")

    # ========================================================================
    # DAILY DIGEST GLOBAL (tous les symboles)
    # ========================================================================
    def create_global_digest_scheduler():
        """Crée UN SEUL scheduler de digest pour tous les symboles"""
        tg_config = cfg.get("telegram", {})

        if not tg_config.get("send_daily_digest", False):
            logger.info("[DIGEST] Daily digest désactivé dans config")
            return None

        from apscheduler.schedulers.background import BackgroundScheduler
        from reporting.daily_digest import send_daily_digest
        import pytz

        # Récupérer les horaires
        raw_times = tg_config.get("daily_digest_times", ["10:00", "19:00"])
        if not isinstance(raw_times, list):
            raw_times = [raw_times]

        # Créer scheduler
        tz = pytz.timezone("Europe/Zurich")
        digest_scheduler = BackgroundScheduler(timezone=tz)

        # Utiliser le premier orchestrateur pour l'envoi Telegram
        first_orch = orchestrators[0] if orchestrators else None

        def digest_job(hour, minute):
            logger.info(f"[DIGEST] Génération digest {hour:02d}:{minute:02d} pour {len(enabled_symbols)} symboles")
            if first_orch:
                try:
                    send_daily_digest(first_orch._send_telegram, enabled_symbols, tz_name="Europe/Zurich")
                    logger.info(f"[DIGEST] ✅ Digest envoyé avec succès")
                except Exception as e:
                    logger.error(f"[DIGEST] ❌ Erreur envoi digest : {e}")

        # Ajouter les jobs
        for time_str in raw_times:
            try:
                hh, mm = map(int, time_str.split(":"))
                job_id = f"global_digest_{hh:02d}{mm:02d}"
                digest_scheduler.add_job(
                    digest_job,
                    "cron",
                    id=job_id,
                    hour=hh,
                    minute=mm,
                    args=(hh, mm),
                    replace_existing=True  # FIX 2026-03-05: ajusté pour débloquer trading
                )
                logger.info(f"[DIGEST] ✅ Job programmé : {time_str}")
            except Exception as e:
                logger.error(f"[DIGEST] ❌ Erreur programmation {time_str} : {e}")

        digest_scheduler.start()
        logger.info(f"[DIGEST] ✅ Scheduler démarré pour {len(raw_times)} horaires")
        return digest_scheduler

    # Créer le scheduler de digest global
    digest_sched = create_global_digest_scheduler()

    # ========================================================================
    # AUTO-OPTIMIZATION GLOBALE - DÉSACTIVÉ (2025-12-27)
    # Remplacé par Windows Task Scheduler : scripts/weekly_optimizer.py
    # Exécution : tous les jours à 23h00 via setup_windows_scheduler.ps1
    # ========================================================================
    # def create_global_auto_optimizer():
    #     """Crée UN SEUL scheduler d'auto-optimization"""
    #     try:
    #         from optimization.auto_optimizer import start_auto_optimization
    #         logger.info("[MAIN] Démarrage auto-optimization globale...")
    #         auto_optimizer = start_auto_optimization()
    #         logger.info("[MAIN] ✅ Auto-optimization activée")
    #         return auto_optimizer
    #     except Exception as e:
    #         logger.warning(f"[MAIN] Auto-optimization non disponible : {e}")
    #         return None
    #
    # # Créer l'auto-optimizer global
    # auto_optimizer = create_global_auto_optimizer()
    logger.info("[MAIN] Auto-optimization gérée par Windows Task Scheduler (23h00 quotidien)")

    # ========================================================================
    # DÉMARRAGE DES MONITORS - AUDIT 2025-12-27
    # ========================================================================
    # 1. Trade Outcome Tracker (feedback loop P&L réel)
    if OUTCOME_TRACKER_AVAILABLE and start_outcome_tracking is not None:
        try:
            start_outcome_tracking()
            logger.info("[MAIN] ✅ Trade Outcome Tracker démarré")
        except Exception as e:
            logger.warning(f"[MAIN] Trade Outcome Tracker non démarré: {e}")
    else:
        logger.info("[MAIN] Trade Outcome Tracker non disponible")

    # 2. Loss Pattern Analyzer (initialisation)
    if LOSS_ANALYZER_AVAILABLE and get_loss_analyzer is not None:
        try:
            analyzer = get_loss_analyzer()
            logger.info("[MAIN] ✅ Loss Pattern Analyzer initialisé")
        except Exception as e:
            logger.warning(f"[MAIN] Loss Pattern Analyzer non initialisé: {e}")
    else:
        logger.info("[MAIN] Loss Pattern Analyzer non disponible")

    async def main():
        # Lancer tous les orchestrateurs + Telegram en parallèle
        tasks = [orch.run() for orch in orchestrators]
        tasks.append(tg_client.run())
        logger.info(f"[MAIN] Lancement de {len(orchestrators)} orchestrateurs en parallèle...")
        await asyncio.gather(*tasks)

    asyncio.run(main())
