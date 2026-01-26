# config/profiles/__init__.py
"""
Module de gestion des profils de trading (SCALPING / SWING).
"""

from typing import Dict, Any, Optional
from . import scalping, swing

# Profils disponibles
PROFILES = {
    "SCALPING": scalping,
    "SWING": swing
}

# Mapping timeframe -> profil par défaut
TIMEFRAME_TO_PROFILE = {
    "M1": "SCALPING",
    "M5": "SCALPING",
    "M15": "SCALPING",
    "M30": "SCALPING",
    "H1": "SWING",
    "H4": "SWING",
    "D1": "SWING"
}


def get_profile_for_timeframe(timeframe: str) -> str:
    """Retourne le nom du profil approprié pour un timeframe donné."""
    return TIMEFRAME_TO_PROFILE.get(timeframe.upper(), "SCALPING")


def get_profile_module(profile_name: str):
    """Retourne le module du profil."""
    return PROFILES.get(profile_name.upper(), scalping)


def get_position_manager_config(timeframe: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """Retourne la config Position Manager pour le timeframe/profil donné."""
    if profile is None:
        profile = get_profile_for_timeframe(timeframe)
    module = get_profile_module(profile)
    return module.get_position_manager_config(timeframe)


def get_structure_agent_config(timeframe: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """Retourne la config Structure Agent pour le timeframe/profil donné."""
    if profile is None:
        profile = get_profile_for_timeframe(timeframe)
    module = get_profile_module(profile)
    return module.get_structure_agent_config(timeframe)


def get_smart_money_agent_config(timeframe: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """Retourne la config Smart Money Agent pour le timeframe/profil donné."""
    if profile is None:
        profile = get_profile_for_timeframe(timeframe)
    module = get_profile_module(profile)
    return module.get_smart_money_agent_config(timeframe)


def get_ote_config(timeframe: str, profile: Optional[str] = None) -> Dict[str, float]:
    """Retourne la config OTE pour le timeframe/profil donné."""
    if profile is None:
        profile = get_profile_for_timeframe(timeframe)
    module = get_profile_module(profile)
    return module.get_ote_config(timeframe)


def get_risk_management_config(profile: str = "SCALPING") -> Dict[str, Any]:
    """Retourne la config Risk Management pour le profil donné."""
    module = get_profile_module(profile)
    return module.RISK_MANAGEMENT


def get_full_config(timeframe: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """Retourne la configuration complète pour le timeframe/profil donné."""
    if profile is None:
        profile = get_profile_for_timeframe(timeframe)
    module = get_profile_module(profile)
    return module.get_full_config(timeframe)
