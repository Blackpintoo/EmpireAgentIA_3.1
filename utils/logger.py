# utils/logger.py
import logging
from logging.handlers import RotatingFileHandler  # FIX 2026-07-26: rotation des logs
import sys
import os
import re
from typing import Any

# --------- Redaction (masquage secrets) ---------
_MASK = "****"
# FIX 2026-08-02 : la cle Finnhub circulait EN CLAIR dans logs/empire_agent.log,
# via l'URL complete d'un appel en echec (…/calendar/economic?…&token=…).
# Le masquage ne couvrait que Telegram et MT5. Toute cle d'API du .env est
# desormais masquee, et le motif generique attrape aussi les jetons passes en
# parametre d'URL par du code qui ne serait pas passe par cette liste.
_SENSITIVE = [
    ("TELEGRAM_BOT_TOKEN",   os.environ.get("TELEGRAM_BOT_TOKEN")),
    ("MT5_PASSWORD",         os.environ.get("MT5_PASSWORD")),
    ("FINNHUB_API_KEY",      os.environ.get("FINNHUB_API_KEY")),
    ("ALPHA_VANTAGE_API_KEY", os.environ.get("ALPHA_VANTAGE_API_KEY")),
    ("NEWSAPI_KEY",          os.environ.get("NEWSAPI_KEY")),
    ("CRYPTOPANIC_TOKEN",    os.environ.get("CRYPTOPANIC_TOKEN")),
]

_TOKEN_PATTERN = re.compile(r"\b\d{9,}:[A-Za-z0-9_\-]{20,}\b")  # tokens Telegram-like
# Jetons passes en parametre d'URL : ?token=…, &api_key=…, &apikey=…
_URL_TOKEN_PATTERN = re.compile(
    r"([?&](?:token|api_?key|apikey|access_token)=)[^&\s]+", re.IGNORECASE)

def _redact(val: Any) -> Any:
    try:
        s = str(val)
        for _, secret in _SENSITIVE:
            if secret:
                s = s.replace(secret, _MASK)
        s = _TOKEN_PATTERN.sub(_MASK, s)
        s = _URL_TOKEN_PATTERN.sub(r"\1" + _MASK, s)
        return s
    except Exception:
        return val

class RedactingFormatter(logging.Formatter):
    # FIX 2026-07-30 (P1): l'ancienne version faisait str() sur TOUS les
    # arguments de log, y compris les nombres. Toute ligne utilisant %d,
    # %.2f, %0.4f... levait alors "TypeError: must be real number, not str"
    # au moment du formatage. Le message etait perdu et un bloc
    # "--- Logging error ---" partait sur stderr. Le defaut touchait
    # l'ensemble du code, pas seulement les tests (ex.
    # risk_manager.is_daily_limit_reached, qui logue avec %.2f%%).
    # Deux corrections :
    #   1. on ne masque que les valeurs textuelles ; un nombre ne peut pas
    #      contenir de secret, il reste donc intact ;
    #   2. on ne mute plus le LogRecord — il est partage par tous les
    #      handlers, et la mutation faussait le formatage des suivants.
    def format(self, record: logging.LogRecord) -> str:
        try:
            original_msg = record.msg
            original_args = record.args
            if isinstance(record.msg, (str, bytes)):
                record.msg = _redact(record.msg)
            if isinstance(record.args, dict):
                record.args = {
                    k: (_redact(v) if isinstance(v, (str, bytes)) else v)
                    for k, v in record.args.items()
                }
            elif record.args:
                record.args = tuple(
                    _redact(a) if isinstance(a, (str, bytes)) else a
                    for a in record.args
                )
            try:
                return super().format(record)
            finally:
                record.msg = original_msg
                record.args = original_args
        except Exception:
            return super().format(record)

class _DynamicStdoutHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.setStream(sys.stdout)
        except ValueError:
            self.stream = sys.stdout
        super().emit(record)


def _build_formatter() -> logging.Formatter:
    # (2026-01-06) Format stable pour analyse: time | level | name | message
    # Compatible avec parsing CSV/grep pour extraction des patterns
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    # Par défaut, logging utilise l'heure locale de la machine (OK pour Europe/Zurich)
    return RedactingFormatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

def _ensure_handlers(logger: logging.Logger) -> None:
    """Ajoute une sortie console (optionnelle) et fichier (optionnelle) sans doublon."""
    if getattr(logger, "_empire_handlers_initialized", False):
        return

    level_name = os.getenv("EMPIRE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = _build_formatter()

    # Console
    if os.getenv("EMPIRE_CONSOLE", "1") == "1":
        ch = _DynamicStdoutHandler()
        ch.setFormatter(fmt)
        ch.setLevel(level)
        logger.addHandler(ch)

    # Fichier - par défaut logs/empire_agent.log (2026-01-06)
    log_path = os.getenv("EMPIRE_LOG_FILE", "logs/empire_agent.log")
    if log_path:
        # Création du dossier si nécessaire
        try:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
        except Exception:
            pass
        # FIX 2026-07-26: rotation obligatoire — empire_agent.log avait atteint 231 Mo
        # sans jamais tourner. Réglable via EMPIRE_LOG_MAX_MB / EMPIRE_LOG_BACKUPS.
        try:
            max_mb = float(os.getenv("EMPIRE_LOG_MAX_MB", "20"))
        except Exception:
            max_mb = 20.0
        try:
            backups = int(os.getenv("EMPIRE_LOG_BACKUPS", "5"))
        except Exception:
            backups = 5
        try:
            fh = RotatingFileHandler(
                log_path,
                maxBytes=int(max_mb * 1024 * 1024),
                backupCount=backups,
                encoding="utf-8",
                delay=True,
            )
            fh.setFormatter(fmt)
            fh.setLevel(level)
            logger.addHandler(fh)
        except Exception:
            pass  # Ignore si le fichier ne peut pas être créé

    # Évite la multiplication des logs via la racine
    logger.propagate = False
    logger._empire_handlers_initialized = True  # type: ignore[attr-defined]

# --------- Logger public ---------
logger = logging.getLogger("empire_agent_ia")
_ensure_handlers(logger)
