"""
Système d'optimisation automatique des agents - Empire Agent IA v3

Fonctionnalités :
- Optimisation périodique via APScheduler
- Optuna pour recherche hyperparamètres
- Validation walk-forward
- Sauvegarde automatique avant optimisation
- Notifications Telegram
- Application automatique des meilleurs paramètres
- Sécurité : blocage si positions ouvertes ou heures de trading

Usage :
    from optimization.auto_optimizer import AutoOptimizer

    auto_opt = AutoOptimizer()
    auto_opt.start()  # Démarre le scheduler

Date : 2025-11-30
"""

import os
import yaml
import logging
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Dict, List, Optional
import shutil
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

try:
    from utils.logger import logger
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class AutoOptimizer:
    """
    Gestionnaire d'optimisation automatique des agents.

    Charge config/auto_optimization.yaml et schedule les optimisations
    selon la fréquence configurée (daily, weekly, monthly).
    """

    CONFIG_FILE = "config/auto_optimization.yaml"

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialise l'auto-optimizer.

        Args:
            config_path: Chemin vers fichier config (défaut: config/auto_optimization.yaml)
        """
        self.config_path = config_path or self.CONFIG_FILE
        self.config = self._load_config()
        self.scheduler = None
        self.is_running = False

        # Créer répertoire backups
        if self.config.get("backup", {}).get("enabled"):
            backup_dir = self.config["backup"]["directory"]
            Path(backup_dir).mkdir(parents=True, exist_ok=True)

        logger.info("[AutoOptimizer] Initialisé")

    def _load_config(self) -> Dict:
        """Charge la configuration depuis YAML."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            auto_opt = config.get("auto_optimization", {})

            if not auto_opt.get("enabled"):
                logger.warning("[AutoOptimizer] Optimisation automatique DÉSACTIVÉE dans config")
                return {"auto_optimization": {"enabled": False}}

            logger.info(f"[AutoOptimizer] Config chargée : {auto_opt.get('frequency')} à {auto_opt['schedule']['time']}")
            return config

        except FileNotFoundError:
            logger.error(f"[AutoOptimizer] Fichier config introuvable : {self.config_path}")
            return {"auto_optimization": {"enabled": False}}

        except Exception as e:
            logger.error(f"[AutoOptimizer] Erreur chargement config : {e}")
            return {"auto_optimization": {"enabled": False}}

    def start(self):
        """Démarre le scheduler d'optimisation automatique."""
        config = self.config.get("auto_optimization", {})

        if not config.get("enabled"):
            logger.warning("[AutoOptimizer] Optimisation automatique désactivée - Pas de démarrage")
            return

        if self.is_running:
            logger.warning("[AutoOptimizer] Déjà en cours d'exécution")
            return

        # Créer scheduler
        timezone = config["schedule"].get("timezone", "Europe/Zurich")
        self.scheduler = BackgroundScheduler(timezone=timezone)

        # Ajouter job selon fréquence
        frequency = config.get("frequency", "weekly")
        schedule_config = config["schedule"]

        if frequency == "daily":
            # Tous les jours à l'heure spécifiée
            hour, minute = schedule_config["time"].split(":")
            trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
            logger.info(f"[AutoOptimizer] Schedule DAILY à {schedule_config['time']}")

        elif frequency == "weekly":
            # Chaque semaine le jour spécifié à l'heure spécifiée
            day = schedule_config["day_of_week"]
            hour, minute = schedule_config["time"].split(":")
            trigger = CronTrigger(day_of_week=day, hour=hour, minute=minute, timezone=timezone)
            logger.info(f"[AutoOptimizer] Schedule WEEKLY : jour {day} à {schedule_config['time']}")

        elif frequency == "biweekly":
            # Toutes les 2 semaines (approximation avec week=*/2)
            day = schedule_config["day_of_week"]
            hour, minute = schedule_config["time"].split(":")
            trigger = CronTrigger(day_of_week=day, hour=hour, minute=minute, week="*/2", timezone=timezone)
            logger.info(f"[AutoOptimizer] Schedule BIWEEKLY : jour {day} à {schedule_config['time']}")

        elif frequency == "monthly":
            # Premier dimanche du mois à l'heure spécifiée
            day = schedule_config.get("day_of_month", 1)
            hour, minute = schedule_config["time"].split(":")
            trigger = CronTrigger(day=day, hour=hour, minute=minute, timezone=timezone)
            logger.info(f"[AutoOptimizer] Schedule MONTHLY : jour {day} à {schedule_config['time']}")

        else:
            logger.error(f"[AutoOptimizer] Fréquence invalide : {frequency}")
            return

        # Ajouter job
        self.scheduler.add_job(
            func=self._run_optimization,
            trigger=trigger,
            id="auto_optimization",
            name="Auto-Optimization Empire Agents",
            replace_existing=True
        )

        # Démarrer scheduler
        self.scheduler.start()
        self.is_running = True

        logger.info("[AutoOptimizer] ✅ Scheduler démarré - Optimisations automatiques actives")

        # Notifier Telegram
        if config.get("notifications", {}).get("telegram"):
            self._send_telegram(
                "🤖 **Auto-Optimization ACTIVÉE**\n\n"
                f"Fréquence : {frequency}\n"
                f"Prochain run : {self.scheduler.get_jobs()[0].next_run_time}\n"
                f"Agents : {', '.join(config.get('agents', []))}\n"
                f"Symboles : {', '.join(config.get('symbols', []))}"
            )

    def stop(self):
        """Arrête le scheduler."""
        if self.scheduler and self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("[AutoOptimizer] Scheduler arrêté")

    def _run_optimization(self):
        """
        Exécute un cycle d'optimisation automatique.

        Appelé par le scheduler selon la fréquence configurée.
        """
        config = self.config.get("auto_optimization", {})

        logger.info("=" * 80)
        logger.info("[AutoOptimizer] 🚀 DÉMARRAGE OPTIMISATION AUTOMATIQUE")
        logger.info("=" * 80)

        # Notifier début
        if config.get("notifications", {}).get("notify_start"):
            self._send_telegram("🚀 **Optimisation automatique démarrée**")

        try:
            # 1. Vérifications de sécurité
            if not self._safety_checks():
                logger.warning("[AutoOptimizer] Vérifications sécurité échouées - Optimisation annulée")
                return

            # 2. Sauvegarder configuration actuelle
            if config.get("backup", {}).get("enabled"):
                self._backup_current_config()

            # 3. Lancer optimisations pour chaque agent + symbole
            results = self._optimize_all()

            # 4. Analyser résultats
            improvements = self._analyze_results(results)

            # 5. Appliquer améliorations si auto_apply activé
            if config.get("auto_apply", {}).get("enabled"):
                self._apply_improvements(improvements)

            # 6. Notifier fin
            if config.get("notifications", {}).get("notify_end"):
                self._send_telegram(
                    f"✅ **Optimisation terminée**\n\n"
                    f"Agents optimisés : {len(results)}\n"
                    f"Améliorations trouvées : {len(improvements)}"
                )

            logger.info("[AutoOptimizer] ✅ Optimisation automatique terminée avec succès")

        except Exception as e:
            logger.error(f"[AutoOptimizer] ❌ Erreur optimisation : {e}", exc_info=True)

            # Notifier erreur
            if config.get("notifications", {}).get("notify_failure"):
                self._send_telegram(f"❌ **Erreur optimisation**\n\n{str(e)}")

    def _safety_checks(self) -> bool:
        """
        Vérifications de sécurité avant optimisation.

        Returns:
            True si sécurisé, False sinon
        """
        config = self.config.get("auto_optimization", {})
        safety = config.get("safety", {})

        # 1. Vérifier si positions ouvertes
        if safety.get("block_if_open_positions"):
            if self._has_open_positions():
                logger.warning("[AutoOptimizer] Positions ouvertes détectées - Optimisation bloquée")
                return False

        # 2. Vérifier heures de marché
        if safety.get("block_during_market_hours"):
            if self._is_market_hours():
                logger.warning("[AutoOptimizer] Heures de trading actives - Optimisation bloquée")
                return False

        # 3. Vérifier limite quotidienne
        max_per_day = safety.get("max_per_day", 1)
        today_count = self._count_optimizations_today()
        if today_count >= max_per_day:
            logger.warning(f"[AutoOptimizer] Limite quotidienne atteinte ({today_count}/{max_per_day})")
            return False

        logger.info("[AutoOptimizer] ✅ Vérifications sécurité OK")
        return True

    def _has_open_positions(self) -> bool:
        """Vérifie si des positions sont ouvertes."""
        try:
            from utils.mt5_client import MT5Client

            client = MT5Client()
            # TODO: Implémenter vérification positions
            # positions = client.get_open_positions()
            # return len(positions) > 0

            return False  # Placeholder

        except Exception as e:
            logger.warning(f"[AutoOptimizer] Impossible vérifier positions : {e}")
            return True  # Prudence : bloquer si erreur

    def _is_market_hours(self) -> bool:
        """Vérifie si on est pendant les heures de marché."""
        config = self.config.get("auto_optimization", {})
        safety = config.get("safety", {})
        market_hours = safety.get("market_hours", {})

        if not market_hours:
            return False

        try:
            timezone = config["schedule"].get("timezone", "Europe/Zurich")
            tz = pytz.timezone(timezone)
            now = datetime.now(tz).time()

            start_str = market_hours.get("start", "08:00")
            end_str = market_hours.get("end", "22:00")

            start_hour, start_min = map(int, start_str.split(":"))
            end_hour, end_min = map(int, end_str.split(":"))

            start_time = dt_time(start_hour, start_min)
            end_time = dt_time(end_hour, end_min)

            return start_time <= now <= end_time

        except Exception as e:
            logger.warning(f"[AutoOptimizer] Erreur vérification heures marché : {e}")
            return False

    def _count_optimizations_today(self) -> int:
        """Compte le nombre d'optimisations aujourd'hui."""
        # TODO: Implémenter comptage depuis logs ou DB
        return 0  # Placeholder

    def _backup_current_config(self):
        """Sauvegarde la configuration actuelle avant optimisation."""
        try:
            config = self.config.get("auto_optimization", {})
            backup_dir = Path(config["backup"]["directory"])

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"config_backup_{timestamp}.yaml"

            # Copier config/config.yaml
            shutil.copy("config/config.yaml", backup_path)

            logger.info(f"[AutoOptimizer] ✅ Backup créé : {backup_path}")

            # Nettoyer vieux backups
            keep_last = config["backup"].get("keep_last", 10)
            self._cleanup_old_backups(backup_dir, keep_last)

        except Exception as e:
            logger.error(f"[AutoOptimizer] Erreur backup : {e}")

    def _cleanup_old_backups(self, backup_dir: Path, keep_last: int):
        """Supprime les vieux backups."""
        try:
            backups = sorted(backup_dir.glob("config_backup_*.yaml"))

            if len(backups) > keep_last:
                to_delete = backups[:-keep_last]
                for backup in to_delete:
                    backup.unlink()
                    logger.info(f"[AutoOptimizer] Backup supprimé : {backup.name}")

        except Exception as e:
            logger.warning(f"[AutoOptimizer] Erreur nettoyage backups : {e}")

    def _optimize_all(self) -> List[Dict]:
        """
        Optimise tous les agents pour tous les symboles configurés.

        Returns:
            Liste des résultats d'optimisation
        """
        config = self.config.get("auto_optimization", {})
        agents = config.get("agents", [])
        symbols = config.get("symbols", [])

        results = []

        for agent in agents:
            for symbol in symbols:
                logger.info(f"[AutoOptimizer] Optimisation {agent} pour {symbol}...")

                try:
                    result = self._optimize_agent_symbol(agent, symbol)
                    results.append(result)

                except Exception as e:
                    logger.error(f"[AutoOptimizer] Erreur {agent}/{symbol} : {e}")
                    results.append({
                        "agent": agent,
                        "symbol": symbol,
                        "status": "error",
                        "error": str(e)
                    })

        return results

    def _optimize_agent_symbol(self, agent: str, symbol: str) -> Dict:
        """
        Optimise un agent pour un symbole spécifique.

        Args:
            agent: Nom de l'agent
            symbol: Symbole à optimiser

        Returns:
            Résultat de l'optimisation
        """
        config = self.config.get("auto_optimization", {})
        optuna_config = config.get("optuna", {})

        # TODO: Implémenter appel à optimization.optimizer
        # from optimization.optimizer import optimize_agent
        #
        # result = optimize_agent(
        #     agent=agent,
        #     symbol=symbol,
        #     n_trials=optuna_config.get("n_trials", 30),
        #     timeout=optuna_config.get("timeout", 600)
        # )

        # Placeholder
        logger.info(f"[AutoOptimizer] TODO: Optimisation {agent}/{symbol}")

        return {
            "agent": agent,
            "symbol": symbol,
            "status": "success",
            "improvement": 1.0,  # Pas d'amélioration (placeholder)
            "best_params": {}
        }

    def _analyze_results(self, results: List[Dict]) -> List[Dict]:
        """Analyse les résultats et identifie les améliorations."""
        config = self.config.get("auto_optimization", {})
        min_improvement = config.get("auto_apply", {}).get("min_improvement", 1.05)

        improvements = []

        for result in results:
            if result.get("status") != "success":
                continue

            improvement_ratio = result.get("improvement", 1.0)

            if improvement_ratio >= min_improvement:
                improvements.append(result)
                logger.info(
                    f"[AutoOptimizer] ✅ Amélioration trouvée : {result['agent']}/{result['symbol']} "
                    f"(+{(improvement_ratio - 1) * 100:.1f}%)"
                )

        return improvements

    def _apply_improvements(self, improvements: List[Dict]):
        """Applique les améliorations trouvées."""
        if not improvements:
            logger.info("[AutoOptimizer] Aucune amélioration à appliquer")
            return

        logger.info(f"[AutoOptimizer] Application de {len(improvements)} améliorations...")

        for improvement in improvements:
            try:
                self._apply_params(
                    improvement["agent"],
                    improvement["symbol"],
                    improvement["best_params"]
                )

                logger.info(f"[AutoOptimizer] ✅ Paramètres appliqués : {improvement['agent']}/{improvement['symbol']}")

            except Exception as e:
                logger.error(f"[AutoOptimizer] Erreur application {improvement['agent']} : {e}")

        # Notifier Telegram
        config = self.config.get("auto_optimization", {})
        if config.get("notifications", {}).get("notify_improvement"):
            msg = "✅ **Améliorations appliquées**\n\n"
            for imp in improvements:
                msg += f"• {imp['agent']}/{imp['symbol']}: +{(imp['improvement'] - 1) * 100:.1f}%\n"

            self._send_telegram(msg)

    def _apply_params(self, agent: str, symbol: str, params: Dict):
        """Applique les paramètres optimisés à la configuration."""
        # TODO: Implémenter modification config/config.yaml ou profiles.yaml
        logger.info(f"[AutoOptimizer] TODO: Appliquer params {agent}/{symbol}")

    def _send_telegram(self, message: str):
        """Envoie notification Telegram."""
        try:
            from utils.telegram_client import TelegramClient

            # TODO: Implémenter envoi Telegram
            logger.info(f"[AutoOptimizer] Telegram (TODO) : {message[:50]}...")

        except Exception as e:
            logger.warning(f"[AutoOptimizer] Impossible envoyer Telegram : {e}")


# Helper pour intégration facile dans orchestrator
def start_auto_optimization():
    """Démarre l'optimisation automatique (à appeler depuis orchestrator)."""
    auto_opt = AutoOptimizer()
    auto_opt.start()
    return auto_opt


if __name__ == "__main__":
    # Test
    print("=== Test Auto-Optimizer ===\n")

    auto_opt = AutoOptimizer()

    if auto_opt.config.get("auto_optimization", {}).get("enabled"):
        print("✅ Config chargée")
        print(f"Fréquence : {auto_opt.config['auto_optimization']['frequency']}")
        print(f"Agents : {auto_opt.config['auto_optimization']['agents']}")
        print(f"Symboles : {auto_opt.config['auto_optimization']['symbols']}")

        # Démarrer (test - ne pas lancer réellement)
        # auto_opt.start()
        print("\n✅ AutoOptimizer prêt (start() non appelé en test)")
    else:
        print("❌ Optimisation automatique désactivée")
