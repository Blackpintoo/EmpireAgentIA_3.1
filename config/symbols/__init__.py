# config/symbols/__init__.py
"""
Ajustements de paramètres par symbole selon leur volatilité.
Les symboles sont regroupés par catégorie (forex, crypto, indices, matières premières).
"""

from typing import Dict, Any, Optional

# ============================================================
# AJUSTEMENTS SCALPING PAR SYMBOLE (M15 comme référence)
# ============================================================

SCALPING_ADJUSTMENTS = {
    # ----------------- FOREX MAJEURS -----------------
    "EURUSD": {
        "eq_tolerance_pts": 5,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },
    "GBPUSD": {
        "eq_tolerance_pts": 7,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },
    "USDJPY": {
        "eq_tolerance_pts": 5,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },
    "AUDUSD": {
        "eq_tolerance_pts": 4,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },
    "USDCAD": {
        "eq_tolerance_pts": 5,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },
    "USDCHF": {
        "eq_tolerance_pts": 5,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },

    # ----------------- FOREX CROISÉS -----------------
    "GBPJPY": {
        "eq_tolerance_pts": 10,
        "sl_mult": 1.2,
        "tp_mult": 1.5,
        "atr_mult": 1.3,
        "volatility_class": "medium"
    },
    "EURJPY": {
        "eq_tolerance_pts": 8,
        "sl_mult": 1.1,
        "tp_mult": 1.4,
        "atr_mult": 1.3,
        "volatility_class": "medium"
    },
    "EURGBP": {
        "eq_tolerance_pts": 4,
        "sl_mult": 1.0,
        "tp_mult": 1.3,
        "atr_mult": 1.2,
        "volatility_class": "low"
    },

    # ----------------- MATIÈRES PREMIÈRES -----------------
    "XAUUSD": {
        "eq_tolerance_pts": 30,
        "sl_mult": 1.3,
        "tp_mult": 1.5,
        "atr_mult": 1.5,
        "volatility_class": "high"
    },
    "XAGUSD": {
        "eq_tolerance_pts": 25,
        "sl_mult": 1.3,
        "tp_mult": 1.5,
        "atr_mult": 1.5,
        "volatility_class": "high"
    },
    "CL-OIL": {
        "eq_tolerance_pts": 20,
        "sl_mult": 1.2,
        "tp_mult": 1.4,
        "atr_mult": 1.4,
        "volatility_class": "medium"
    },

    # ----------------- INDICES -----------------
    "DJ30": {
        "eq_tolerance_pts": 20,
        "sl_mult": 1.2,
        "tp_mult": 1.4,
        "atr_mult": 1.4,
        "volatility_class": "medium"
    },
    "NAS100": {
        "eq_tolerance_pts": 25,
        "sl_mult": 1.2,
        "tp_mult": 1.4,
        "atr_mult": 1.4,
        "volatility_class": "medium"
    },
    "GER40": {
        "eq_tolerance_pts": 20,
        "sl_mult": 1.2,
        "tp_mult": 1.4,
        "atr_mult": 1.4,
        "volatility_class": "medium"
    },
    "SPX500": {
        "eq_tolerance_pts": 15,
        "sl_mult": 1.1,
        "tp_mult": 1.4,
        "atr_mult": 1.3,
        "volatility_class": "medium"
    },

    # ----------------- CRYPTO -----------------
    "BTCUSD": {
        "eq_tolerance_pts": 50,
        "sl_mult": 1.5,
        "tp_mult": 1.8,
        "atr_mult": 1.8,
        "volatility_class": "very_high"
    },
    "ETHUSD": {
        "eq_tolerance_pts": 30,
        "sl_mult": 1.4,
        "tp_mult": 1.6,
        "atr_mult": 1.6,
        "volatility_class": "very_high"
    },
    "BNBUSD": {
        "eq_tolerance_pts": 25,
        "sl_mult": 1.4,
        "tp_mult": 1.6,
        "atr_mult": 1.6,
        "volatility_class": "high"
    },
    "LTCUSD": {
        "eq_tolerance_pts": 20,
        "sl_mult": 1.3,
        "tp_mult": 1.5,
        "atr_mult": 1.5,
        "volatility_class": "high"
    },
    "ADAUSD": {
        "eq_tolerance_pts": 15,
        "sl_mult": 1.3,
        "tp_mult": 1.5,
        "atr_mult": 1.5,
        "volatility_class": "high"
    },
    "SOLUSD": {
        "eq_tolerance_pts": 25,
        "sl_mult": 1.4,
        "tp_mult": 1.6,
        "atr_mult": 1.6,
        "volatility_class": "very_high"
    }
}

# ============================================================
# AJUSTEMENTS SWING PAR SYMBOLE (H4 comme référence)
# ============================================================

SWING_ADJUSTMENTS = {
    # ----------------- FOREX MAJEURS -----------------
    "EURUSD": {
        "eq_tolerance_pts": 20,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },
    "GBPUSD": {
        "eq_tolerance_pts": 25,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },
    "USDJPY": {
        "eq_tolerance_pts": 20,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },
    "AUDUSD": {
        "eq_tolerance_pts": 15,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },
    "USDCAD": {
        "eq_tolerance_pts": 18,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },
    "USDCHF": {
        "eq_tolerance_pts": 18,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },

    # ----------------- FOREX CROISÉS -----------------
    "GBPJPY": {
        "eq_tolerance_pts": 40,
        "sl_mult": 2.2,
        "tp_mult": 4.5,
        "atr_mult": 2.8,
        "volatility_class": "medium"
    },
    "EURJPY": {
        "eq_tolerance_pts": 30,
        "sl_mult": 2.1,
        "tp_mult": 4.2,
        "atr_mult": 2.6,
        "volatility_class": "medium"
    },
    "EURGBP": {
        "eq_tolerance_pts": 15,
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "atr_mult": 2.5,
        "volatility_class": "low"
    },

    # ----------------- MATIÈRES PREMIÈRES -----------------
    "XAUUSD": {
        "eq_tolerance_pts": 100,
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "atr_mult": 3.0,
        "volatility_class": "high"
    },
    "XAGUSD": {
        "eq_tolerance_pts": 80,
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "atr_mult": 3.0,
        "volatility_class": "high"
    },
    "CL-OIL": {
        "eq_tolerance_pts": 60,
        "sl_mult": 2.3,
        "tp_mult": 4.5,
        "atr_mult": 2.8,
        "volatility_class": "medium"
    },

    # ----------------- INDICES -----------------
    "DJ30": {
        "eq_tolerance_pts": 80,
        "sl_mult": 2.3,
        "tp_mult": 4.5,
        "atr_mult": 2.8,
        "volatility_class": "medium"
    },
    "NAS100": {
        "eq_tolerance_pts": 100,
        "sl_mult": 2.3,
        "tp_mult": 4.5,
        "atr_mult": 2.8,
        "volatility_class": "medium"
    },
    "GER40": {
        "eq_tolerance_pts": 80,
        "sl_mult": 2.3,
        "tp_mult": 4.5,
        "atr_mult": 2.8,
        "volatility_class": "medium"
    },
    "SPX500": {
        "eq_tolerance_pts": 60,
        "sl_mult": 2.2,
        "tp_mult": 4.2,
        "atr_mult": 2.6,
        "volatility_class": "medium"
    },

    # ----------------- CRYPTO -----------------
    "BTCUSD": {
        "eq_tolerance_pts": 200,
        "sl_mult": 3.0,
        "tp_mult": 6.0,
        "atr_mult": 3.5,
        "volatility_class": "very_high"
    },
    "ETHUSD": {
        "eq_tolerance_pts": 150,
        "sl_mult": 2.8,
        "tp_mult": 5.5,
        "atr_mult": 3.2,
        "volatility_class": "very_high"
    },
    "BNBUSD": {
        "eq_tolerance_pts": 120,
        "sl_mult": 2.7,
        "tp_mult": 5.0,
        "atr_mult": 3.0,
        "volatility_class": "high"
    },
    "LTCUSD": {
        "eq_tolerance_pts": 100,
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "atr_mult": 3.0,
        "volatility_class": "high"
    },
    "ADAUSD": {
        "eq_tolerance_pts": 80,
        "sl_mult": 2.5,
        "tp_mult": 5.0,
        "atr_mult": 3.0,
        "volatility_class": "high"
    },
    "SOLUSD": {
        "eq_tolerance_pts": 130,
        "sl_mult": 2.8,
        "tp_mult": 5.5,
        "atr_mult": 3.2,
        "volatility_class": "very_high"
    }
}

# ============================================================
# CATÉGORIES DE SYMBOLES
# ============================================================

SYMBOL_CATEGORIES = {
    "forex_majors": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"],
    "forex_crosses": ["GBPJPY", "EURJPY", "EURGBP"],
    "metals": ["XAUUSD", "XAGUSD"],
    "oil": ["CL-OIL"],
    "indices": ["DJ30", "NAS100", "GER40", "SPX500"],
    "crypto": ["BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"]
}

# Symboles activés (conforme à profiles.yaml)
ENABLED_SYMBOLS = [
    # Cryptos
    "BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD",
    # Forex
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
    # Matières premières
    "XAUUSD", "XAGUSD", "CL-OIL",
    # Indices
    "DJ30", "NAS100", "GER40"
]


def get_symbol_category(symbol: str) -> Optional[str]:
    """Retourne la catégorie d'un symbole."""
    symbol = symbol.upper()
    for category, symbols in SYMBOL_CATEGORIES.items():
        if symbol in symbols:
            return category
    return None


def get_symbol_adjustments(symbol: str, profile: str = "SCALPING") -> Dict[str, Any]:
    """
    Retourne les ajustements spécifiques pour un symbole et un profil.

    Args:
        symbol: Le symbole (ex: "BTCUSD")
        profile: "SCALPING" ou "SWING"

    Returns:
        Dict avec les ajustements ou dict vide si symbole non trouvé
    """
    symbol = symbol.upper()
    profile = profile.upper()

    if profile == "SCALPING":
        return SCALPING_ADJUSTMENTS.get(symbol, {})
    elif profile == "SWING":
        return SWING_ADJUSTMENTS.get(symbol, {})

    return {}


def get_volatility_class(symbol: str, profile: str = "SCALPING") -> str:
    """Retourne la classe de volatilité d'un symbole."""
    adjustments = get_symbol_adjustments(symbol, profile)
    return adjustments.get("volatility_class", "medium")


def merge_with_base_config(base_config: Dict[str, Any], symbol: str, profile: str = "SCALPING") -> Dict[str, Any]:
    """
    Fusionne la config de base avec les ajustements spécifiques au symbole.

    Args:
        base_config: Configuration de base du profil
        symbol: Le symbole
        profile: "SCALPING" ou "SWING"

    Returns:
        Configuration fusionnée
    """
    adjustments = get_symbol_adjustments(symbol, profile)
    if not adjustments:
        return base_config.copy()

    merged = base_config.copy()

    # Fusionner les ajustements (les ajustements écrasent les valeurs de base)
    for key, value in adjustments.items():
        if key != "volatility_class":  # Ne pas inclure la classe de volatilité
            merged[key] = value

    return merged


def is_crypto(symbol: str) -> bool:
    """Vérifie si un symbole est une crypto."""
    return symbol.upper() in SYMBOL_CATEGORIES.get("crypto", [])


def is_forex(symbol: str) -> bool:
    """Vérifie si un symbole est du forex."""
    symbol = symbol.upper()
    return symbol in SYMBOL_CATEGORIES.get("forex_majors", []) or \
           symbol in SYMBOL_CATEGORIES.get("forex_crosses", [])


def is_index(symbol: str) -> bool:
    """Vérifie si un symbole est un indice."""
    return symbol.upper() in SYMBOL_CATEGORIES.get("indices", [])


def is_commodity(symbol: str) -> bool:
    """Vérifie si un symbole est une matière première."""
    symbol = symbol.upper()
    return symbol in SYMBOL_CATEGORIES.get("metals", []) or \
           symbol in SYMBOL_CATEGORIES.get("oil", [])
