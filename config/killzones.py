# config/killzones.py
"""
Module de gestion des Killzones ICT (heures de trading optimales).
Les trades doivent être filtrés par les killzones pour maximiser la probabilité de succès.
"""

from datetime import datetime, time, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pytz

# ============================================================
# DÉFINITION DES KILLZONES (heures UTC)
# ============================================================

KILLZONES = {
    "asian": {
        "name": "Asian Session",
        "start": "00:00",
        "end": "05:00",
        "pairs": ["USDJPY", "AUDUSD", "EURJPY", "GBPJPY", "XAUUSD",
                  "BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"],
        "description": "Session asiatique - Tokyo, Sydney",
        "expected_scalping_trades": "2-4 trades",
        "volatility": "low"
    },
    "london": {
        "name": "London Session",
        "start": "07:00",
        "end": "10:00",
        "pairs": ["EURUSD", "GBPUSD", "EURGBP", "USDCHF", "XAUUSD", "XAGUSD",
                  "GER40", "BTCUSD", "ETHUSD"],
        "description": "Ouverture Londres - Haute liquidité EUR/GBP",
        "expected_scalping_trades": "4-6 trades",
        "volatility": "high"
    },
    "new_york": {
        "name": "New York Session",
        "start": "12:00",
        "end": "15:00",
        "pairs": ["EURUSD", "GBPUSD", "USDCAD", "DJ30", "NAS100", "SPX500",
                  "XAUUSD", "CL-OIL", "BTCUSD", "ETHUSD"],
        "description": "Ouverture New York - Overlap avec Londres",
        "expected_scalping_trades": "5-8 trades",
        "volatility": "very_high"
    },
    "london_close": {
        "name": "London Close",
        "start": "15:00",
        "end": "17:00",
        "pairs": ["EURUSD", "GBPUSD", "XAUUSD", "BTCUSD", "ETHUSD"],
        "description": "Fermeture Londres - Consolidation",
        "expected_scalping_trades": "2-4 trades",
        "volatility": "medium"
    },
    "crypto_24h": {
        "name": "Crypto 24/7",
        "start": "00:00",
        "end": "23:59",
        "pairs": ["BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"],
        "description": "Crypto trade 24/7 mais meilleures opportunités pendant les sessions traditionnelles",
        "expected_scalping_trades": "Variable",
        "volatility": "high"
    }
}

# Sessions étendues pour le swing trading (moins restrictif)
SWING_SESSIONS = {
    "europe_extended": {
        "name": "Europe Extended",
        "start": "06:00",
        "end": "18:00",
        "pairs": "all",
        "description": "Session étendue pour swing trading"
    },
    "us_extended": {
        "name": "US Extended",
        "start": "12:00",
        "end": "21:00",
        "pairs": "all",
        "description": "Session US étendue pour swing trading"
    }
}

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def _parse_time(time_str: str) -> time:
    """Parse une chaîne HH:MM en objet time."""
    h, m = map(int, time_str.split(":"))
    return time(hour=h, minute=m, tzinfo=timezone.utc)


def get_current_utc_time() -> datetime:
    """Retourne l'heure actuelle en UTC."""
    return datetime.now(timezone.utc)


def get_current_local_time(tz_name: str = "Europe/Zurich") -> datetime:
    """Retourne l'heure actuelle dans le fuseau horaire spécifié."""
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)


def is_in_killzone(kz_name: str, current_time: Optional[datetime] = None) -> bool:
    """
    Vérifie si l'heure actuelle est dans une killzone donnée.

    Args:
        kz_name: Nom de la killzone (asian, london, new_york, london_close)
        current_time: Heure à vérifier (UTC). Si None, utilise l'heure actuelle.

    Returns:
        True si dans la killzone, False sinon
    """
    if kz_name not in KILLZONES:
        return False

    kz = KILLZONES[kz_name]
    if current_time is None:
        current_time = get_current_utc_time()

    # Convertir en UTC si nécessaire
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    current = current_time.time().replace(tzinfo=timezone.utc)
    start = _parse_time(kz["start"])
    end = _parse_time(kz["end"])

    # Gérer le cas où la session traverse minuit
    if start <= end:
        return start <= current <= end
    else:
        return current >= start or current <= end


def get_active_killzones(current_time: Optional[datetime] = None) -> List[str]:
    """
    Retourne la liste des killzones actuellement actives.

    Args:
        current_time: Heure à vérifier (UTC). Si None, utilise l'heure actuelle.

    Returns:
        Liste des noms de killzones actives
    """
    active = []
    for kz_name in KILLZONES:
        if is_in_killzone(kz_name, current_time):
            active.append(kz_name)
    return active


def is_symbol_in_killzone(symbol: str, current_time: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """
    Vérifie si un symbole est éligible au trading dans les killzones actuelles.

    Args:
        symbol: Le symbole à vérifier
        current_time: Heure à vérifier (UTC). Si None, utilise l'heure actuelle.

    Returns:
        Tuple (est_éligible, liste_des_killzones_actives)
    """
    symbol = symbol.upper()
    active_killzones = get_active_killzones(current_time)

    if not active_killzones:
        return False, []

    eligible_killzones = []
    for kz_name in active_killzones:
        kz = KILLZONES[kz_name]
        if symbol in kz["pairs"]:
            eligible_killzones.append(kz_name)

    return len(eligible_killzones) > 0, eligible_killzones


def get_next_killzone(symbol: str, current_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Retourne la prochaine killzone pour un symbole donné.

    Args:
        symbol: Le symbole
        current_time: Heure actuelle (UTC). Si None, utilise l'heure actuelle.

    Returns:
        Dict avec les infos de la prochaine killzone ou None
    """
    symbol = symbol.upper()
    if current_time is None:
        current_time = get_current_utc_time()

    current = current_time.time()

    # Trouver les killzones où ce symbole est éligible
    eligible_kz = []
    for kz_name, kz in KILLZONES.items():
        if symbol in kz["pairs"]:
            start = _parse_time(kz["start"])
            eligible_kz.append((kz_name, kz, start))

    if not eligible_kz:
        return None

    # Trier par heure de début
    eligible_kz.sort(key=lambda x: x[2].replace(tzinfo=None))

    # Trouver la prochaine
    for kz_name, kz, start in eligible_kz:
        start_naive = start.replace(tzinfo=None)
        current_naive = current.replace(tzinfo=None)
        if start_naive > current_naive:
            return {
                "name": kz_name,
                "start": kz["start"],
                "end": kz["end"],
                "description": kz["description"]
            }

    # Si aucune trouvée aujourd'hui, retourner la première de demain
    if eligible_kz:
        kz_name, kz, start = eligible_kz[0]
        return {
            "name": kz_name,
            "start": kz["start"],
            "end": kz["end"],
            "description": kz["description"],
            "tomorrow": True
        }

    return None


def should_trade_now(symbol: str, profile: str = "SCALPING",
                     current_time: Optional[datetime] = None,
                     strict: bool = True) -> Tuple[bool, str]:
    """
    Détermine si un symbole devrait être tradé maintenant selon les killzones.

    Args:
        symbol: Le symbole à vérifier
        profile: "SCALPING" ou "SWING"
        current_time: Heure à vérifier (UTC). Si None, utilise l'heure actuelle.
        strict: Si True, n'autorise que pendant les killzones. Si False, autorise toujours avec avertissement.

    Returns:
        Tuple (devrait_trader, raison)
    """
    symbol = symbol.upper()

    # Les cryptos peuvent toujours trader (mais mieux pendant les sessions)
    from config.symbols import is_crypto
    if is_crypto(symbol):
        is_eligible, active_kz = is_symbol_in_killzone(symbol, current_time)
        if is_eligible:
            return True, f"Crypto {symbol} dans killzone(s): {', '.join(active_kz)}"
        else:
            # Crypto hors killzone - autorisé mais signalé
            return True, f"Crypto {symbol} hors killzone optimale - volatilité potentiellement réduite"

    # Pour le swing trading, on est moins strict
    if profile.upper() == "SWING":
        # Vérifier si on est dans une session étendue
        if current_time is None:
            current_time = get_current_utc_time()
        current = current_time.time().replace(tzinfo=timezone.utc)

        # Vérifier les sessions swing
        for session_name, session in SWING_SESSIONS.items():
            start = _parse_time(session["start"])
            end = _parse_time(session["end"])
            if start <= current <= end:
                return True, f"Swing trading autorisé - session {session['name']}"

        if not strict:
            return True, "Swing trading hors session - risque accru"
        return False, "Hors session de swing trading"

    # Pour le scalping, vérifier les killzones
    is_eligible, active_kz = is_symbol_in_killzone(symbol, current_time)

    if is_eligible:
        return True, f"{symbol} éligible dans killzone(s): {', '.join(active_kz)}"

    if not strict:
        return True, f"{symbol} hors killzone - scalping non recommandé mais autorisé"

    next_kz = get_next_killzone(symbol, current_time)
    if next_kz:
        tomorrow = " (demain)" if next_kz.get("tomorrow") else ""
        return False, f"{symbol} hors killzone. Prochaine: {next_kz['name']} à {next_kz['start']} UTC{tomorrow}"

    return False, f"{symbol} n'a pas de killzone définie"


def get_killzone_info(kz_name: str) -> Optional[Dict[str, Any]]:
    """Retourne les informations d'une killzone."""
    return KILLZONES.get(kz_name)


def get_all_killzones() -> Dict[str, Dict[str, Any]]:
    """Retourne toutes les killzones."""
    return KILLZONES.copy()


def get_symbols_for_current_killzone(current_time: Optional[datetime] = None) -> List[str]:
    """
    Retourne la liste des symboles éligibles dans les killzones actuelles.

    Args:
        current_time: Heure à vérifier (UTC). Si None, utilise l'heure actuelle.

    Returns:
        Liste des symboles éligibles
    """
    active_kz = get_active_killzones(current_time)
    eligible_symbols = set()

    for kz_name in active_kz:
        kz = KILLZONES[kz_name]
        eligible_symbols.update(kz["pairs"])

    return list(eligible_symbols)
