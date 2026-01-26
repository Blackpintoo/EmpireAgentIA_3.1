# config/trading_profiles.py
"""
Gestionnaire centralisé des profils de trading.
Fusionne les configurations de profil (SCALPING/SWING) avec les ajustements par symbole.
"""

from typing import Dict, Any, Optional, Tuple
import logging
import os

logger = logging.getLogger(__name__)

# Import des modules de configuration
try:
    from config.profiles import (
        get_profile_for_timeframe,
        get_position_manager_config,
        get_structure_agent_config,
        get_smart_money_agent_config,
        get_ote_config,
        get_risk_management_config,
        get_full_config,
        TIMEFRAME_TO_PROFILE
    )
    from config.symbols import (
        get_symbol_adjustments,
        get_volatility_class,
        merge_with_base_config,
        is_crypto,
        is_forex,
        is_index,
        is_commodity,
        ENABLED_SYMBOLS
    )
    from config.killzones import (
        should_trade_now,
        get_active_killzones,
        is_symbol_in_killzone,
        get_next_killzone
    )
    PROFILES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"[TradingProfiles] Import error: {e}. Using fallback mode.")
    PROFILES_AVAILABLE = False


# Profil actif global (peut être changé via variable d'environnement)
# Valeurs: "AUTO" (détection par timeframe), "SCALPING", "SWING"
_env_profile = os.environ.get("TRADING_PROFILE", "AUTO").upper()
ACTIVE_PROFILE = _env_profile if _env_profile in ("SCALPING", "SWING", "AUTO") else "AUTO"

# Timeframe par défaut selon le profil
DEFAULT_TIMEFRAMES = {
    "SCALPING": "M15",
    "SWING": "H4",
    "AUTO": "M15"  # Par défaut M15 en mode AUTO
}


def get_active_profile() -> str:
    """Retourne le profil actif actuel."""
    return ACTIVE_PROFILE


def set_active_profile(profile: str) -> None:
    """Définit le profil actif."""
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = profile.upper()
    logger.info(f"[TradingProfiles] Profil actif: {ACTIVE_PROFILE}")


def get_default_timeframe(profile: Optional[str] = None) -> str:
    """Retourne le timeframe par défaut pour un profil."""
    if profile is None:
        profile = ACTIVE_PROFILE
    return DEFAULT_TIMEFRAMES.get(profile.upper(), "M15")


def get_trading_config(
    symbol: str,
    timeframe: Optional[str] = None,
    profile: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration de trading complète pour un symbole.
    Fusionne le profil de base avec les ajustements spécifiques au symbole.

    Args:
        symbol: Le symbole (ex: "BTCUSD")
        timeframe: Le timeframe (ex: "M15"). Si None, utilise le défaut du profil.
        profile: Le profil ("SCALPING" ou "SWING"). Si None, déduit du timeframe.

    Returns:
        Configuration complète fusionnée
    """
    symbol = symbol.upper()

    # Déterminer le profil
    if profile is None or profile == "AUTO":
        if timeframe:
            # Mode AUTO: le profil est déterminé par le timeframe
            profile = get_profile_for_timeframe(timeframe) if PROFILES_AVAILABLE else "SCALPING"
        else:
            # Pas de timeframe spécifié, utiliser SCALPING par défaut
            profile = "SCALPING"

    # Déterminer le timeframe
    if timeframe is None:
        timeframe = get_default_timeframe(profile)

    if not PROFILES_AVAILABLE:
        return _fallback_config(symbol, timeframe, profile)

    # Obtenir la config de base du profil
    base_config = get_full_config(timeframe, profile)

    # Obtenir les ajustements spécifiques au symbole
    symbol_adjustments = get_symbol_adjustments(symbol, profile)

    # Fusionner les configurations
    config = base_config.copy()

    # Fusionner les ajustements dans les agents
    if symbol_adjustments:
        # Structure Agent
        if "structure_agent" in config:
            for key in ["eq_tolerance_pts", "sl_mult", "tp_mult"]:
                if key in symbol_adjustments:
                    if key == "eq_tolerance_pts":
                        # Convertir en ratio pour smc_eq_tolerance
                        # eq_tolerance_pts est en points, on le garde pour smart_money
                        pass
                    config["structure_agent"][key] = symbol_adjustments[key]

        # Smart Money Agent
        if "smart_money_agent" in config:
            for key in ["eq_tolerance_pts", "sl_mult", "tp_mult"]:
                if key in symbol_adjustments:
                    config["smart_money_agent"][key] = symbol_adjustments[key]

        # Position Manager - Trailing ATR mult
        if "atr_mult" in symbol_adjustments and "position_manager" in config:
            if "trailing" in config["position_manager"]:
                config["position_manager"]["trailing"]["atr_mult"] = symbol_adjustments["atr_mult"]

    # Ajouter les métadonnées
    config["symbol"] = symbol
    config["volatility_class"] = get_volatility_class(symbol, profile)

    return config


def get_position_manager_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    profile: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration Position Manager pour un symbole.

    Args:
        symbol: Le symbole
        timeframe: Le timeframe (ex: "M15")
        profile: Le profil ("SCALPING" ou "SWING")

    Returns:
        Configuration Position Manager
    """
    config = get_trading_config(symbol, timeframe, profile)
    return config.get("position_manager", {})


def get_structure_agent_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    profile: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration Structure Agent pour un symbole.

    Args:
        symbol: Le symbole
        timeframe: Le timeframe
        profile: Le profil

    Returns:
        Configuration Structure Agent
    """
    config = get_trading_config(symbol, timeframe, profile)
    return config.get("structure_agent", {})


def get_smart_money_agent_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    profile: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration Smart Money Agent pour un symbole.

    Args:
        symbol: Le symbole
        timeframe: Le timeframe
        profile: Le profil

    Returns:
        Configuration Smart Money Agent
    """
    config = get_trading_config(symbol, timeframe, profile)
    return config.get("smart_money_agent", {})


def get_ote_for_symbol(
    symbol: str,
    timeframe: Optional[str] = None,
    profile: Optional[str] = None
) -> Dict[str, float]:
    """
    Retourne la configuration OTE pour un symbole.

    Args:
        symbol: Le symbole
        timeframe: Le timeframe
        profile: Le profil

    Returns:
        Configuration OTE
    """
    config = get_trading_config(symbol, timeframe, profile)
    return config.get("ote", {})


def should_trade_symbol(
    symbol: str,
    profile: Optional[str] = None,
    strict: bool = False
) -> Tuple[bool, str]:
    """
    Détermine si un symbole devrait être tradé maintenant.
    Vérifie les killzones et autres conditions.

    Args:
        symbol: Le symbole
        profile: Le profil ("SCALPING" ou "SWING")
        strict: Si True, applique les killzones strictement

    Returns:
        Tuple (devrait_trader, raison)
    """
    if not PROFILES_AVAILABLE:
        return True, "Profiles module not available - trading allowed"

    if profile is None:
        profile = ACTIVE_PROFILE

    return should_trade_now(symbol, profile, strict=strict)


def validate_config(config: Dict[str, Any]) -> Tuple[bool, list]:
    """
    Valide qu'une configuration est cohérente.

    Args:
        config: Configuration à valider

    Returns:
        Tuple (est_valide, liste_erreurs)
    """
    errors = []

    # Vérifier que tp_mult > sl_mult
    for agent_key in ["structure_agent", "smart_money_agent"]:
        if agent_key in config:
            agent = config[agent_key]
            tp = agent.get("tp_mult", 0)
            sl = agent.get("sl_mult", 0)
            if tp > 0 and sl > 0 and tp <= sl:
                errors.append(f"{agent_key}: tp_mult ({tp}) devrait être > sl_mult ({sl})")

    # Vérifier le Position Manager
    if "position_manager" in config:
        pm = config["position_manager"]

        # Break-even RR doit être positif
        if "break_even" in pm:
            be_rr = pm["break_even"].get("rr", 0)
            if be_rr <= 0:
                errors.append(f"break_even.rr ({be_rr}) doit être > 0")

        # Partials RR doivent être croissants
        if "partials" in pm:
            partials = pm["partials"]
            prev_rr = 0
            for i, p in enumerate(partials):
                rr = p.get("rr", 0)
                if rr <= prev_rr:
                    errors.append(f"partials[{i}].rr ({rr}) doit être > partials[{i-1}].rr ({prev_rr})")
                prev_rr = rr

        # Trailing start_rr doit être positif
        if "trailing" in pm:
            start_rr = pm["trailing"].get("start_rr", 0)
            if start_rr <= 0:
                errors.append(f"trailing.start_rr ({start_rr}) doit être > 0")

    # Vérifier l'OTE
    if "ote" in config:
        ote = config["ote"]
        zone_low = ote.get("zone_low", 0)
        zone_high = ote.get("zone_high", 0)
        if zone_low >= zone_high:
            errors.append(f"ote.zone_low ({zone_low}) doit être < zone_high ({zone_high})")

    return len(errors) == 0, errors


def log_config(symbol: str, config: Dict[str, Any]) -> None:
    """Log la configuration utilisée pour debugging."""
    logger.info(f"[TradingProfiles] Config pour {symbol}:")
    logger.info(f"  - Profil: {config.get('profile', 'N/A')}")
    logger.info(f"  - Timeframe: {config.get('timeframe', 'N/A')}")
    logger.info(f"  - Volatilité: {config.get('volatility_class', 'N/A')}")

    if "position_manager" in config:
        pm = config["position_manager"]
        if "break_even" in pm:
            logger.info(f"  - Break-Even RR: {pm['break_even'].get('rr', 'N/A')}")
        if "trailing" in pm:
            logger.info(f"  - Trailing ATR mult: {pm['trailing'].get('atr_mult', 'N/A')}")

    if "structure_agent" in config:
        sa = config["structure_agent"]
        logger.info(f"  - Structure swing_window: {sa.get('swing_window', 'N/A')}")
        logger.info(f"  - Structure sl/tp mult: {sa.get('sl_mult', 'N/A')}/{sa.get('tp_mult', 'N/A')}")


def _fallback_config(symbol: str, timeframe: str, profile: str) -> Dict[str, Any]:
    """Configuration de fallback si les modules ne sont pas disponibles."""
    return {
        "profile": profile,
        "timeframe": timeframe,
        "symbol": symbol,
        "position_manager": {
            "enabled": True,
            "break_even": {"rr": 1.0, "offset_points": 0.0},
            "partials": [
                {"rr": 1.0, "close_frac": 0.5},
                {"rr": 2.0, "close_frac": 0.3}
            ],
            "trailing": {
                "enabled": True,
                "start_rr": 1.8,
                "atr_timeframe": "M5",
                "atr_period": 14,
                "atr_mult": 1.6,
                "lock_rr": 0.3
            }
        },
        "structure_agent": {
            "lookback": 300,
            "swing_window": 20,
            "retest_bars": 3,
            "atr_period": 14,
            "sl_mult": 1.5,
            "tp_mult": 2.5,
            "smc_enabled": True
        },
        "smart_money_agent": {
            "timeframe": timeframe,
            "lookback": 320,
            "eq_tolerance_pts": 6,
            "sl_mult": 1.5,
            "tp_mult": 2.2
        },
        "ote": {
            "zone_low": 0.62,
            "sweet_spot": 0.705,
            "zone_high": 0.79
        },
        "risk_management": {
            "risk_per_trade": 0.01,
            "daily_loss_cap": 0.02
        },
        "volatility_class": "medium"
    }


# ============================================================
# FONCTIONS D'INITIALISATION
# ============================================================

def initialize_profiles(profile: Optional[str] = None) -> None:
    """
    Initialise le système de profils.
    Appelé au démarrage de l'application.

    Args:
        profile: Profil à activer. Si None, utilise la variable d'environnement ou SCALPING.
    """
    if profile:
        set_active_profile(profile)

    logger.info(f"[TradingProfiles] Initialisation - Profil actif: {ACTIVE_PROFILE}")
    logger.info(f"[TradingProfiles] Timeframe par défaut: {get_default_timeframe()}")

    if PROFILES_AVAILABLE:
        logger.info(f"[TradingProfiles] Symboles activés: {len(ENABLED_SYMBOLS)}")
    else:
        logger.warning("[TradingProfiles] Mode fallback actif - modules non disponibles")


def get_all_configs_summary() -> Dict[str, Dict[str, Any]]:
    """
    Retourne un résumé des configurations pour tous les symboles activés.
    Utile pour le debugging et la validation.

    Returns:
        Dict {symbol: config_summary}
    """
    if not PROFILES_AVAILABLE:
        return {}

    summary = {}
    for symbol in ENABLED_SYMBOLS:
        config = get_trading_config(symbol)
        is_valid, errors = validate_config(config)

        summary[symbol] = {
            "profile": config.get("profile"),
            "timeframe": config.get("timeframe"),
            "volatility_class": config.get("volatility_class"),
            "is_valid": is_valid,
            "errors": errors if errors else None,
            "sl_mult": config.get("structure_agent", {}).get("sl_mult"),
            "tp_mult": config.get("structure_agent", {}).get("tp_mult"),
            "be_rr": config.get("position_manager", {}).get("break_even", {}).get("rr"),
            "trailing_atr_mult": config.get("position_manager", {}).get("trailing", {}).get("atr_mult")
        }

    return summary
