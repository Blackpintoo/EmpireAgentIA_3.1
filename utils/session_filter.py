# utils/session_filter.py
# FIX 2026-02-20: Filtre de session par classe d'actif (étape 5.5)
"""
Prime hours par instrument. En dehors de ces heures, le min_score_for_proposal
est augmenté de 50% pour n'accepter que les signaux très forts.

Configurable par symbole dans overrides.yaml sous la clé "prime_hours_utc".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# FIX 2026-02-20: Heures de trading optimales identifiées par l'audit
_DEFAULT_PRIME_HOURS = {
    "XAUUSD": [{"start": 7, "end": 17}],                      # London
    "SP500":  [{"start": 13, "end": 20}],                      # NY cash (13:30-20:00)
    "NAS100": [{"start": 13, "end": 20}],                      # NY cash
    "EURUSD": [{"start": 7, "end": 17}],                       # London + NY overlap
    "USDJPY": [{"start": 7, "end": 17}],                       # London + NY overlap
    "GBPUSD": [{"start": 7, "end": 17}],                       # London + NY overlap
    "AUDUSD": [{"start": 0, "end": 8}, {"start": 22, "end": 24}],  # Asie + Sydney
    # Crypto: pas de restriction (24/7)
}

# Symboles crypto: aucune restriction horaire
_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "LTCUSD", "DOGEUSD"}


def _is_crypto(symbol: str) -> bool:
    s = symbol.upper()
    return any(c in s for c in ("BTC", "ETH", "SOL", "BNB", "LTC", "DOGE"))


def is_in_prime_hours(symbol: str, prime_hours_cfg: Optional[List[Dict]] = None) -> bool:
    """
    Vérifie si l'heure UTC courante est dans les prime hours du symbole.

    Args:
        symbol: Symbole à vérifier
        prime_hours_cfg: Configuration depuis overrides.yaml (optionnel)

    Returns:
        True si dans les prime hours ou si crypto (toujours True)
    """
    symbol = symbol.upper()

    # Crypto: toujours en prime hours
    if _is_crypto(symbol):
        return True

    # Récupérer la config des prime hours
    if prime_hours_cfg is None:
        prime_hours_cfg = _DEFAULT_PRIME_HOURS.get(symbol)

    # Pas de config = toujours en prime hours (pas de restriction)
    if not prime_hours_cfg:
        return True

    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour

    for window in prime_hours_cfg:
        start = int(window.get("start", 0))
        end = int(window.get("end", 24))

        if start <= end:
            # Plage normale: ex 7-17
            if start <= current_hour < end:
                return True
        else:
            # Plage qui chevauche minuit: ex 22-8
            if current_hour >= start or current_hour < end:
                return True

    return False


def get_adjusted_min_score(
    symbol: str,
    base_min_score: float,
    prime_hours_cfg: Optional[List[Dict]] = None,
) -> Tuple[float, bool]:
    """
    Retourne le min_score_for_proposal ajusté selon les prime hours.

    Args:
        symbol: Symbole
        base_min_score: Score minimum de base
        prime_hours_cfg: Config prime hours depuis overrides

    Returns:
        Tuple[adjusted_score, is_prime_hours]
    """
    in_prime = is_in_prime_hours(symbol, prime_hours_cfg)

    if in_prime:
        return base_min_score, True
    else:
        # FIX 2026-02-20: hors prime hours, +50% sur le min score
        adjusted = base_min_score * 1.5
        logger.debug(
            f"[SESSION_FILTER] {symbol} hors prime hours: "
            f"min_score {base_min_score:.2f} → {adjusted:.2f}"
        )
        return adjusted, False


def is_eod_restricted(symbol: str, last_entry_time_utc: str = "18:00") -> bool:
    """
    Vérifie si on est après l'heure limite d'entrée pour les instruments non-crypto.

    Args:
        symbol: Symbole
        last_entry_time_utc: Heure limite format "HH:MM"

    Returns:
        True si les nouvelles positions non-crypto sont interdites
    """
    # FIX 2026-02-20: Crypto exemptée (marchés 24/7)
    if _is_crypto(symbol):
        return False

    try:
        now_utc = datetime.now(timezone.utc)
        parts = last_entry_time_utc.split(":")
        limit_hour = int(parts[0])
        limit_minute = int(parts[1]) if len(parts) > 1 else 0

        if now_utc.hour > limit_hour or (now_utc.hour == limit_hour and now_utc.minute >= limit_minute):
            return True
    except Exception:
        pass

    return False


def should_close_eod(symbol: str, eod_close_time_utc: str = "19:30") -> bool:
    """
    Vérifie si on doit fermer les positions pour la fin de journée.

    Args:
        symbol: Symbole
        eod_close_time_utc: Heure de fermeture format "HH:MM"

    Returns:
        True si les positions non-crypto doivent être fermées
    """
    # FIX 2026-02-20: Crypto exemptée (marchés 24/7)
    if _is_crypto(symbol):
        return False

    try:
        now_utc = datetime.now(timezone.utc)
        parts = eod_close_time_utc.split(":")
        close_hour = int(parts[0])
        close_minute = int(parts[1]) if len(parts) > 1 else 0

        if now_utc.hour > close_hour or (now_utc.hour == close_hour and now_utc.minute >= close_minute):
            return True
    except Exception:
        pass

    return False
