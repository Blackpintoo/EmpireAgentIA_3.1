# config/profiles/scalping.py
"""
Profil SCALPING (M5 / M15 / M30)
- 10-20 trades par jour sur 16 symboles
- Temps de détention : 5 minutes à 2 heures maximum
- Win rate cible : 60-70%
- R:R cible : 1:1 à 1.5:1
"""

from typing import Dict, Any

# ============================================================
# POSITION MANAGER - SCALPING
# ============================================================

BREAK_EVEN = {
    "M5": {"rr": 0.5, "offset_points": 2.0},
    "M15": {"rr": 0.6, "offset_points": 3.0},
    "M30": {"rr": 0.7, "offset_points": 5.0}
}

PARTIALS = {
    "M5": [
        {"rr": 0.5, "close_frac": 0.70},
        {"rr": 1.0, "close_frac": 0.20}
        # Reste 10% pour trailing
    ],
    "M15": [
        {"rr": 0.6, "close_frac": 0.60},
        {"rr": 1.2, "close_frac": 0.25}
        # Reste 15% pour trailing
    ],
    "M30": [
        {"rr": 0.8, "close_frac": 0.50},
        {"rr": 1.5, "close_frac": 0.30}
        # Reste 20% pour trailing
    ]
}

TRAILING = {
    "M5": {
        "enabled": True,
        "start_rr": 0.7,
        "atr_timeframe": "M5",
        "atr_period": 7,
        "atr_mult": 1.0,
        "lock_rr": 0.1
    },
    "M15": {
        "enabled": True,
        "start_rr": 0.8,
        "atr_timeframe": "M15",
        "atr_period": 10,
        "atr_mult": 1.2,
        "lock_rr": 0.15
    },
    "M30": {
        "enabled": True,
        "start_rr": 1.0,
        "atr_timeframe": "M30",
        "atr_period": 14,
        "atr_mult": 1.5,
        "lock_rr": 0.2
    }
}

# ============================================================
# STRUCTURE AGENT - SCALPING
# ============================================================

STRUCTURE_AGENT = {
    "M5": {
        "lookback": 60,
        "swing_window": 5,
        "retest_bars": 1,
        "atr_period": 7,
        "sl_mult": 0.8,
        "tp_mult": 1.2,
        "smc_enabled": True,
        "smc_pivot_window": 3,
        "smc_fvg_tolerance": 0.001,
        "smc_eq_tolerance": 0.0005
    },
    "M15": {
        "lookback": 100,
        "swing_window": 8,
        "retest_bars": 2,
        "atr_period": 10,
        "sl_mult": 1.0,
        "tp_mult": 1.5,
        "smc_enabled": True,
        "smc_pivot_window": 5,
        "smc_fvg_tolerance": 0.0015,
        "smc_eq_tolerance": 0.0008
    },
    "M30": {
        "lookback": 150,
        "swing_window": 12,
        "retest_bars": 3,
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 1.8,
        "smc_enabled": True,
        "smc_pivot_window": 8,
        "smc_fvg_tolerance": 0.002,
        "smc_eq_tolerance": 0.001
    }
}

# ============================================================
# SMART MONEY AGENT - SCALPING
# ============================================================

SMART_MONEY_AGENT = {
    "M5": {
        "timeframe": "M5",
        "lookback": 80,
        "trend_lookback": 30,
        "eq_lookback": 5,
        "eq_tolerance_pts": 3,
        "eq_tolerance_ratio": 0.0006,
        "imbalance_lookback": 15,
        "order_block_lookback": 20,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 0.8,
        "tp_mult": 1.0,
        "slope_threshold": 0.0005,
        "atr_period": 7
    },
    "M15": {
        "timeframe": "M15",
        "lookback": 120,
        "trend_lookback": 50,
        "eq_lookback": 8,
        "eq_tolerance_pts": 5,
        "eq_tolerance_ratio": 0.0008,
        "imbalance_lookback": 25,
        "order_block_lookback": 35,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "slope_threshold": 0.0003,
        "atr_period": 10
    },
    "M30": {
        "timeframe": "M30",
        "lookback": 180,
        "trend_lookback": 80,
        "eq_lookback": 12,
        "eq_tolerance_pts": 8,
        "eq_tolerance_ratio": 0.001,
        "imbalance_lookback": 40,
        "order_block_lookback": 50,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 1.2,
        "tp_mult": 1.5,
        "slope_threshold": 0.0002,
        "atr_period": 14
    }
}

# ============================================================
# OTE (Optimal Trade Entry) - SCALPING
# ============================================================

OTE = {
    "M5": {"zone_low": 0.50, "sweet_spot": 0.62, "zone_high": 0.75},
    "M15": {"zone_low": 0.55, "sweet_spot": 0.65, "zone_high": 0.78},
    "M30": {"zone_low": 0.60, "sweet_spot": 0.705, "zone_high": 0.79}
}

# ============================================================
# RISK MANAGEMENT - SCALPING
# ============================================================

RISK_MANAGEMENT = {
    "risk_per_trade": 0.003,      # 0.3% par trade
    "daily_loss_cap": 0.02,       # 2% max par jour
    "max_trades_per_day": 25,
    "max_trades_per_symbol": 3,
    "max_concurrent_trades": 5
}

# ============================================================
# TIMEFRAMES DISPONIBLES
# ============================================================

TIMEFRAMES = ["M5", "M15", "M30"]
DEFAULT_TIMEFRAME = "M15"


def get_position_manager_config(timeframe: str = "M15") -> Dict[str, Any]:
    """Retourne la config Position Manager pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME

    return {
        "enabled": True,
        "break_even": BREAK_EVEN.get(tf, BREAK_EVEN["M15"]),
        "partials": PARTIALS.get(tf, PARTIALS["M15"]),
        "trailing": TRAILING.get(tf, TRAILING["M15"])
    }


def get_structure_agent_config(timeframe: str = "M15") -> Dict[str, Any]:
    """Retourne la config Structure Agent pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return STRUCTURE_AGENT.get(tf, STRUCTURE_AGENT["M15"])


def get_smart_money_agent_config(timeframe: str = "M15") -> Dict[str, Any]:
    """Retourne la config Smart Money Agent pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return SMART_MONEY_AGENT.get(tf, SMART_MONEY_AGENT["M15"])


def get_ote_config(timeframe: str = "M15") -> Dict[str, float]:
    """Retourne la config OTE pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return OTE.get(tf, OTE["M15"])


def get_full_config(timeframe: str = "M15") -> Dict[str, Any]:
    """Retourne la configuration complète pour le timeframe donné."""
    return {
        "profile": "SCALPING",
        "timeframe": timeframe.upper(),
        "position_manager": get_position_manager_config(timeframe),
        "structure_agent": get_structure_agent_config(timeframe),
        "smart_money_agent": get_smart_money_agent_config(timeframe),
        "ote": get_ote_config(timeframe),
        "risk_management": RISK_MANAGEMENT
    }
