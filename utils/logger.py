# utils/logger.py
import logging
import sys
import os
import re
from typing import Any

# --------- Redaction (masquage secrets) ---------
_MASK = "****"
_SENSITIVE = [
    ("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN")),
    ("MT5_PASSWORD",       os.environ.get("MT5_PASSWORD")),
    # ajoute ici d'autres secrets si besoin (API keys, etc.)
]

_TOKEN_PATTERN = re.compile(r"\b\d{9,}:[A-Za-z0-9_\-]{20,}\b")  # tokens Telegram-like

def _redact(val: Any) -> Any:
    try:
        s = str(val)
        for _, secret in _SENSITIVE:
            if secret:
                s = s.replace(secret, _MASK)
        s = _TOKEN_PATTERN.sub(_MASK, s)
        return s
    except Exception:
        return val

class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Masque record.msg et record.args sans casser le logging lazy
        try:
            if record.args:
                safe_args = []
                for a in record.args:
                    safe_args.append(_redact(a))
                record.args = tuple(safe_args)
            # Attention: record.msg n'est pas toujours une str avant format();
            # on laisse logging faire sa concat, mais on applique le masque par sécurité
            record.msg = _redact(record.msg)
        except Exception:
            pass
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
        try:
            fh = logging.FileHandler(log_path, encoding="utf-8")
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
