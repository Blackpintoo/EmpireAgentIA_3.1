# utils/circuit_breaker.py
# FIX 2026-02-20: Circuit-breaker par symbole (étape 2.2)
"""
Circuit-breaker: désactive un symbole pendant 24h après 3 pertes consécutives
dans une fenêtre glissante de 48h.

Persiste l'état dans data/circuit_breaker_state.json.
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.telegram_client import send_telegram_message
except Exception:
    def send_telegram_message(**kwargs):  # type: ignore
        pass

_CB_STATE_PATH = os.path.join("data", "circuit_breaker_state.json")
_GUARDS_LOG_PATH = os.path.join("logs", "guards.log")

# Configuration par défaut
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_WINDOW_HOURS = 48
DEFAULT_COOLDOWN_HOURS = 24


def _log_guard(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(_GUARDS_LOG_PATH), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(_GUARDS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


class CircuitBreaker:
    """Circuit-breaker par symbole."""

    def __init__(
        self,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        window_hours: int = DEFAULT_WINDOW_HOURS,
        cooldown_hours: int = DEFAULT_COOLDOWN_HOURS,
    ):
        self.max_consecutive_losses = max_consecutive_losses
        self.window_hours = window_hours
        self.cooldown_hours = cooldown_hours
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        try:
            if os.path.exists(_CB_STATE_PATH):
                with open(_CB_STATE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(_CB_STATE_PATH), exist_ok=True)
            with open(_CB_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        return self._state.setdefault(symbol.upper(), {
            "losses": [],           # list of ISO timestamps
            "blocked_until": None,  # ISO timestamp or None
        })

    def record_loss(self, symbol: str) -> None:
        """Enregistre une perte pour un symbole."""
        symbol = symbol.upper()
        ss = self._get_symbol_state(symbol)
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Ajouter la perte
        ss["losses"].append(now_iso)

        # Nettoyer les pertes hors fenêtre
        cutoff = now - timedelta(hours=self.window_hours)
        ss["losses"] = [
            ts for ts in ss["losses"]
            if datetime.fromisoformat(ts) >= cutoff
        ]

        # Vérifier si le circuit-breaker doit se déclencher
        if len(ss["losses"]) >= self.max_consecutive_losses:
            blocked_until = now + timedelta(hours=self.cooldown_hours)
            ss["blocked_until"] = blocked_until.isoformat()

            msg = (f"CIRCUIT_BREAKER: {symbol} bloqué pour {self.cooldown_hours}h "
                   f"après {len(ss['losses'])} pertes dans {self.window_hours}h. "
                   f"Déblocage: {blocked_until.strftime('%Y-%m-%d %H:%M UTC')}")
            logger.warning(f"[CIRCUIT_BREAKER] {msg}")
            _log_guard(msg)

            # Notification Telegram
            try:
                send_telegram_message(
                    text=f"[CIRCUIT_BREAKER] {symbol} bloqué {self.cooldown_hours}h "
                         f"({len(ss['losses'])} pertes / {self.window_hours}h)",
                    kind="status"
                )
            except Exception:
                pass

            # Réinitialiser le compteur de pertes
            ss["losses"] = []

        self._save_state()

    def record_win(self, symbol: str) -> None:
        """Enregistre un gain — réinitialise le compteur de pertes consécutives."""
        symbol = symbol.upper()
        ss = self._get_symbol_state(symbol)
        ss["losses"] = []
        self._save_state()

    def is_blocked(self, symbol: str) -> Tuple[bool, str]:
        """
        Vérifie si un symbole est bloqué par le circuit-breaker.

        Returns:
            Tuple[blocked, reason] avec la durée restante dans reason si bloqué
        """
        symbol = symbol.upper()
        ss = self._get_symbol_state(symbol)
        blocked_until = ss.get("blocked_until")

        if blocked_until is None:
            return False, ""

        try:
            blocked_dt = datetime.fromisoformat(blocked_until)
            now = datetime.now(timezone.utc)

            if now < blocked_dt:
                remaining = blocked_dt - now
                hours = remaining.total_seconds() / 3600
                reason = f"CIRCUIT_BREAKER_ACTIVE ({hours:.1f}h restantes)"
                return True, reason
            else:
                # Circuit-breaker expiré, nettoyer
                ss["blocked_until"] = None
                self._save_state()
                return False, ""
        except Exception:
            ss["blocked_until"] = None
            self._save_state()
            return False, ""

    def get_blocked_symbols(self) -> Dict[str, str]:
        """Retourne un dict {symbol: remaining_time} pour tous les symboles bloqués."""
        result = {}
        for symbol in list(self._state.keys()):
            blocked, reason = self.is_blocked(symbol)
            if blocked:
                result[symbol] = reason
        return result

    def get_losses_count(self, symbol: str) -> int:
        """Retourne le nombre de pertes dans la fenêtre glissante."""
        symbol = symbol.upper()
        ss = self._get_symbol_state(symbol)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self.window_hours)
        return len([
            ts for ts in ss.get("losses", [])
            if datetime.fromisoformat(ts) >= cutoff
        ])


# Instance globale
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker(
    max_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    cooldown_hours: int = DEFAULT_COOLDOWN_HOURS,
) -> CircuitBreaker:
    """Récupère ou crée l'instance globale du circuit-breaker."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker(max_losses, window_hours, cooldown_hours)
    return _circuit_breaker
