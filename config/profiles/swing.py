# config/profiles/swing.py
"""
Profil SWING TRADING (H1 / H4 / D1)
- 2-5 trades par semaine sur 16 symboles
- Temps de détention : 1 jour à 2 semaines
- Win rate cible : 45-55% (compensé par R:R élevé)
- R:R cible : 2:1 à 4:1
"""

from typing import Dict, Any

# ============================================================
# POSITION MANAGER - SWING
# ============================================================

BREAK_EVEN = {
    "H1": {"rr": 1.0, "offset_points": 5.0},
    "H4": {"rr": 1.2, "offset_points": 10.0},
    "D1": {"rr": 1.5, "offset_points": 20.0}
}

PARTIALS = {
    "H1": [
        {"rr": 1.0, "close_frac": 0.40},
        {"rr": 2.0, "close_frac": 0.30}
        # Reste 30% pour trailing
    ],
    "H4": [
        {"rr": 1.5, "close_frac": 0.33},
        {"rr": 3.0, "close_frac": 0.33}
        # Reste 34% pour trailing
    ],
    "D1": [
        {"rr": 2.0, "close_frac": 0.30},
        {"rr": 4.0, "close_frac": 0.35}
        # Reste 35% pour trailing
    ]
}

TRAILING = {
    "H1": {
        "enabled": True,
        "start_rr": 1.5,
        "atr_timeframe": "H1",
        "atr_period": 14,
        "atr_mult": 2.0,
        "lock_rr": 0.3
    },
    "H4": {
        "enabled": True,
        "start_rr": 2.0,
        "atr_timeframe": "H4",
        "atr_period": 14,
        "atr_mult": 2.5,
        "lock_rr": 0.5
    },
    "D1": {
        "enabled": True,
        "start_rr": 2.5,
        "atr_timeframe": "D1",
        "atr_period": 7,
        "atr_mult": 3.0,
        "lock_rr": 0.8
    }
}

# ============================================================
# STRUCTURE AGENT - SWING
# ============================================================

STRUCTURE_AGENT = {
    "H1": {
        "lookback": 200,
        "swing_window": 15,
        "retest_bars": 3,
        "atr_period": 14,
        "sl_mult": 1.5,
        "tp_mult": 3.0,
        "smc_enabled": True,
        "smc_pivot_window": 8,
        "smc_fvg_tolerance": 0.002,
        "smc_eq_tolerance": 0.001
    },
    "H4": {
        "lookback": 300,
        "swing_window": 20,
        "retest_bars": 5,
        "atr_period": 14,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "smc_enabled": True,
        "smc_pivot_window": 12,
        "smc_fvg_tolerance": 0.003,
        "smc_eq_tolerance": 0.0015
    },
    "D1": {
        "lookback": 200,
        "swing_window": 30,
        "retest_bars": 8,
        "atr_period": 7,
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "smc_enabled": True,
        "smc_pivot_window": 20,
        "smc_fvg_tolerance": 0.005,
        "smc_eq_tolerance": 0.002
    }
}

# ============================================================
# SMART MONEY AGENT - SWING
# ============================================================

SMART_MONEY_AGENT = {
    "H1": {
        "timeframe": "H1",
        "lookback": 300,
        "trend_lookback": 100,
        "eq_lookback": 15,
        "eq_tolerance_pts": 10,
        "eq_tolerance_ratio": 0.001,
        "imbalance_lookback": 50,
        "order_block_lookback": 80,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 1.5,
        "tp_mult": 3.0,
        "slope_threshold": 0.0001,
        "atr_period": 14
    },
    "H4": {
        "timeframe": "H4",
        "lookback": 400,
        "trend_lookback": 150,
        "eq_lookback": 20,
        "eq_tolerance_pts": 20,
        "eq_tolerance_ratio": 0.0015,
        "imbalance_lookback": 80,
        "order_block_lookback": 120,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "slope_threshold": 0.00008,
        "atr_period": 14
    },
    "D1": {
        "timeframe": "D1",
        "lookback": 250,
        "trend_lookback": 60,
        "eq_lookback": 30,
        "eq_tolerance_pts": 50,
        "eq_tolerance_ratio": 0.002,
        "imbalance_lookback": 100,
        "order_block_lookback": 150,
        "asian_session": {"start": "00:00", "end": "05:00"},
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "slope_threshold": 0.00005,
        "atr_period": 7
    }
}

# ============================================================
# OTE (Optimal Trade Entry) - SWING
# ============================================================

OTE = {
    "H1": {"zone_low": 0.62, "sweet_spot": 0.705, "zone_high": 0.79},
    "H4": {"zone_low": 0.62, "sweet_spot": 0.705, "zone_high": 0.79},
    "D1": {"zone_low": 0.62, "sweet_spot": 0.705, "zone_high": 0.79}
}

# ============================================================
# RISK MANAGEMENT - SWING
# ============================================================

RISK_MANAGEMENT = {
    "risk_per_trade": 0.01,       # 1% par trade
    "weekly_loss_cap": 0.05,      # 5% max par semaine
    "max_trades_per_week": 8,
    "max_trades_per_symbol": 2,
    "max_concurrent_trades": 4
}

# ============================================================
# TIMEFRAMES DISPONIBLES
# ============================================================

TIMEFRAMES = ["H1", "H4", "D1"]
DEFAULT_TIMEFRAME = "H4"


def get_position_manager_config(timeframe: str = "H4") -> Dict[str, Any]:
    """Retourne la config Position Manager pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME

    return {
        "enabled": True,
        "break_even": BREAK_EVEN.get(tf, BREAK_EVEN["H4"]),
        "partials": PARTIALS.get(tf, PARTIALS["H4"]),
        "trailing": TRAILING.get(tf, TRAILING["H4"])
    }


def get_structure_agent_config(timeframe: str = "H4") -> Dict[str, Any]:
    """Retourne la config Structure Agent pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return STRUCTURE_AGENT.get(tf, STRUCTURE_AGENT["H4"])


def get_smart_money_agent_config(timeframe: str = "H4") -> Dict[str, Any]:
    """Retourne la config Smart Money Agent pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return SMART_MONEY_AGENT.get(tf, SMART_MONEY_AGENT["H4"])


def get_ote_config(timeframe: str = "H4") -> Dict[str, float]:
    """Retourne la config OTE pour le timeframe donné."""
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        tf = DEFAULT_TIMEFRAME
    return OTE.get(tf, OTE["H4"])


def get_full_config(timeframe: str = "H4") -> Dict[str, Any]:
    """Retourne la configuration complète pour le timeframe donné."""
    return {
        "profile": "SWING",
        "timeframe": timeframe.upper(),
        "position_manager": get_position_manager_config(timeframe),
        "structure_agent": get_structure_agent_config(timeframe),
        "smart_money_agent": get_smart_money_agent_config(timeframe),
        "ote": get_ote_config(timeframe),
        "risk_management": RISK_MANAGEMENT
    }
