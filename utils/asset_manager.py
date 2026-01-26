"""
PHASE 4 - Asset Manager
Gestion centralisée des paramètres par type d'actif (FOREX, CRYPTOS, INDICES, COMMODITIES)
"""
from __future__ import annotations
import yaml
from pathlib import Path
from datetime import datetime, time
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

from utils.logger import logger


class AssetManager:
    """Gestionnaire de configuration par type d'actif"""

    def __init__(self, config_path: str = "config/asset_config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.symbol_to_type = self._build_symbol_mapping()

    def _load_config(self) -> Dict[str, Any]:
        """Charge la configuration des actifs"""
        if not self.config_path.exists():
            logger.warning(f"[AssetManager] Config file not found: {self.config_path}")
            return {}

        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _build_symbol_mapping(self) -> Dict[str, str]:
        """Construit un mapping symbole → type d'actif"""
        mapping = {}
        for asset_type in ["CRYPTOS", "FOREX", "INDICES", "COMMODITIES"]:
            if asset_type in self.config:
                symbols = self.config[asset_type].get("symbols", [])
                for symbol in symbols:
                    mapping[symbol] = asset_type
        return mapping

    # ========================================================================
    # Identification du type d'actif
    # ========================================================================

    def get_asset_type(self, symbol: str) -> Optional[str]:
        """Retourne le type d'actif pour un symbole"""
        return self.symbol_to_type.get(symbol)

    def is_crypto(self, symbol: str) -> bool:
        return self.get_asset_type(symbol) == "CRYPTOS"

    def is_forex(self, symbol: str) -> bool:
        return self.get_asset_type(symbol) == "FOREX"

    def is_index(self, symbol: str) -> bool:
        return self.get_asset_type(symbol) == "INDICES"

    def is_commodity(self, symbol: str) -> bool:
        return self.get_asset_type(symbol) == "COMMODITIES"

    # ========================================================================
    # Sessions de trading
    # ========================================================================

    def is_trading_allowed(self, symbol: str, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Vérifie si le trading est autorisé pour ce symbole à cette heure
        Returns: (allowed: bool, reason: str)
        """
        if dt is None:
            dt = datetime.now(ZoneInfo("Europe/Zurich"))

        asset_type = self.get_asset_type(symbol)
        if not asset_type or asset_type not in self.config:
            return True, "no_config"

        asset_cfg = self.config[asset_type]
        trading_sessions = asset_cfg.get("trading_sessions", {})

        if not trading_sessions.get("enabled", False):
            return True, "sessions_disabled"

        # Vérifier les blackout periods
        blackout = self._check_blackout_periods(symbol, dt, asset_cfg)
        if blackout:
            return False, blackout

        # Vérifier les sessions spécifiques
        if asset_type == "INDICES":
            return self._check_index_session(symbol, dt, asset_cfg)
        elif asset_type == "FOREX":
            return self._check_forex_session(dt, asset_cfg)
        elif asset_type == "CRYPTOS":
            return self._check_crypto_session(dt, asset_cfg)
        elif asset_type == "COMMODITIES":
            return self._check_commodity_session(dt, asset_cfg)

        return True, "allowed"

    def _check_blackout_periods(self, symbol: str, dt: datetime, asset_cfg: Dict) -> Optional[str]:
        """Vérifie les périodes d'interdiction de trading"""
        blackout_periods = asset_cfg.get("trading_sessions", {}).get("blackout_periods", [])

        for period in blackout_periods:
            day_name = dt.strftime("%A").lower()

            # Si la période spécifie un jour, vérifier d'abord si on est ce jour
            if "day" in period:
                period_day = period["day"].lower()
                # Vérification du week-end
                if period_day == "weekend":
                    if day_name not in ["saturday", "sunday"]:
                        continue  # Pas le week-end, passer à la période suivante
                # Vérification d'un jour spécifique
                elif period_day != day_name:
                    continue  # Pas le bon jour, passer à la période suivante

            # À ce point, soit pas de jour spécifié, soit le jour correspond
            # Vérifier les heures si spécifiées
            if "hours" in period:
                hours_range = period["hours"]
                if isinstance(hours_range, list):
                    for hour_range in hours_range:
                        if self._is_in_time_range(dt.time(), hour_range):
                            return period.get("reason", "blackout_period")
            else:
                # Pas d'heures spécifiées mais le jour correspond = blackout toute la journée
                return period.get("reason", "blackout_period")

        return None

    def _is_in_time_range(self, current_time: time, time_range: str) -> bool:
        """Vérifie si l'heure est dans la plage donnée (format: 'HH:MM-HH:MM')"""
        try:
            start_str, end_str = time_range.split("-")
            start = time(*map(int, start_str.split(":")))
            end = time(*map(int, end_str.split(":")))

            if start <= end:
                return start <= current_time <= end
            else:  # Traverse minuit
                return current_time >= start or current_time <= end
        except:
            return False

    def _check_index_session(self, symbol: str, dt: datetime, asset_cfg: Dict) -> Tuple[bool, str]:
        """Vérifie les sessions pour les indices"""
        schedules = asset_cfg.get("trading_sessions", {}).get("schedules", {})
        symbol_schedule = schedules.get(symbol, [])

        current_time = dt.time()
        for session in symbol_schedule:
            start = time(*map(int, session["start"].split(":")))
            end = time(*map(int, session["end"].split(":")))

            if start <= current_time <= end:
                if session.get("activity") in ["high", "very_high"]:
                    return True, f"{session['name']}_session"
                elif session.get("activity") == "medium":
                    return True, f"{session['name']}_medium"
                else:
                    return False, f"{session['name']}_low_activity"

        return False, "outside_trading_hours"

    def _check_forex_session(self, dt: datetime, asset_cfg: Dict) -> Tuple[bool, str]:
        """Vérifie les sessions FOREX"""
        sessions = asset_cfg.get("trading_sessions", {}).get("sessions", [])
        current_time = dt.time()

        for session in sessions:
            start = time(*map(int, session["start"].split(":")))
            end = time(*map(int, session["end"].split(":")))

            if start <= current_time <= end:
                if session.get("activity") in ["high", "very_high"]:
                    return True, session["name"]

        return False, "low_activity_session"

    def _check_crypto_session(self, dt: datetime, asset_cfg: Dict) -> Tuple[bool, str]:
        """Vérifie les sessions CRYPTO (24/7 mais avec préférences)"""
        # Les cryptos sont 24/7, donc toujours autorisé sauf avoid_periods
        return True, "24/7"

    def _check_commodity_session(self, dt: datetime, asset_cfg: Dict) -> Tuple[bool, str]:
        """Vérifie les sessions COMMODITIES"""
        sessions = asset_cfg.get("trading_sessions", {}).get("sessions", [])
        current_time = dt.time()

        for session in sessions:
            start = time(*map(int, session["start"].split(":")))
            end = time(*map(int, session["end"].split(":")))

            if start <= current_time <= end:
                if session.get("activity") in ["high", "very_high"]:
                    return True, session["name"]

        return False, "low_activity_period"

    # ========================================================================
    # Paramètres de risque
    # ========================================================================

    def get_risk_params(self, symbol: str) -> Dict[str, Any]:
        """Retourne les paramètres de risque pour un symbole"""
        asset_type = self.get_asset_type(symbol)
        if not asset_type or asset_type not in self.config:
            return {}

        return self.config[asset_type].get("risk_params", {})

    def get_risk_per_trade(self, symbol: str) -> float:
        """Retourne le risque par trade pour un symbole (en %)"""
        params = self.get_risk_params(symbol)
        return params.get("risk_per_trade_pct", 0.01)

    def get_max_daily_loss(self, symbol: str) -> float:
        """Retourne la perte max journalière pour un symbole (en %)"""
        params = self.get_risk_params(symbol)
        return params.get("max_daily_loss_pct", 0.02)

    def get_max_parallel_positions(self, symbol: str) -> int:
        """Retourne le nombre max de positions parallèles pour un type d'actif"""
        params = self.get_risk_params(symbol)
        return params.get("max_parallel_positions", 2)

    # ========================================================================
    # Spreads et commissions
    # ========================================================================

    def get_spread_commission(self, symbol: str) -> Dict[str, float]:
        """Retourne spread et commission pour un symbole"""
        asset_type = self.get_asset_type(symbol)
        if not asset_type or asset_type not in self.config:
            return {"avg_spread_points": 20, "commission_per_lot": 5.0}

        spreads = self.config[asset_type].get("spreads_commissions", {})

        # Vérifier si configuration spécifique au symbole
        specific_key = f"{asset_type.lower()[:-1]}_specific"  # CRYPTOS -> crypto_specific
        if specific_key in self.config[asset_type]:
            symbol_cfg = self.config[asset_type][specific_key].get(symbol, {})
            if "avg_spread_points" in symbol_cfg:
                spreads["avg_spread_points"] = symbol_cfg["avg_spread_points"]

        return spreads

    # ========================================================================
    # Timeframes
    # ========================================================================

    def get_timeframes(self, symbol: str) -> Dict[str, Any]:
        """Retourne les timeframes recommandés pour un symbole"""
        asset_type = self.get_asset_type(symbol)
        if not asset_type or asset_type not in self.config:
            return {"primary": "H1", "secondary": ["M30", "H4"]}

        return self.config[asset_type].get("timeframes", {})

    def get_primary_timeframe(self, symbol: str) -> str:
        """Retourne le timeframe principal pour un symbole"""
        tfs = self.get_timeframes(symbol)
        return tfs.get("primary", "H1")

    # ========================================================================
    # Paramètres techniques
    # ========================================================================

    def get_technical_params(self, symbol: str) -> Dict[str, Any]:
        """Retourne les paramètres techniques pour un symbole"""
        asset_type = self.get_asset_type(symbol)
        if not asset_type or asset_type not in self.config:
            return {}

        return self.config[asset_type].get("technical_params", {})

    def get_atr_multipliers(self, symbol: str) -> Tuple[float, float]:
        """Retourne les multiplicateurs ATR (SL, TP) pour un symbole"""
        params = self.get_technical_params(symbol)
        sl_mult = params.get("atr_multiplier_sl", 1.5)
        tp_mult = params.get("atr_multiplier_tp", 2.5)
        return sl_mult, tp_mult

    # ========================================================================
    # Règles globales
    # ========================================================================

    def get_correlation_groups(self) -> List[List[str]]:
        """Retourne les groupes de symboles corrélés (à ne pas trader ensemble)"""
        return self.config.get("global_rules", {}).get("correlation_groups", [])

    def check_correlation_conflict(self, symbol: str, open_positions: List[str]) -> bool:
        """Vérifie si le symbole est corrélé à une position ouverte"""
        groups = self.get_correlation_groups()

        for group in groups:
            if symbol in group:
                # Vérifier si un autre symbole du groupe est en position
                for pos_symbol in open_positions:
                    if pos_symbol in group and pos_symbol != symbol:
                        return True  # Conflit de corrélation
        return False

    def get_max_exposure(self, symbol: str) -> float:
        """Retourne l'exposition max pour le type d'actif (en % du capital)"""
        asset_type = self.get_asset_type(symbol)
        if not asset_type:
            return 0.03  # 3% par défaut

        exposures = self.config.get("global_rules", {}).get("max_exposure", {})
        return exposures.get(asset_type, 0.03)

    def get_priority_order(self) -> List[str]:
        """Retourne l'ordre de priorité des types d'actifs"""
        return self.config.get("global_rules", {}).get("priority_order", [
            "FOREX", "COMMODITIES", "CRYPTOS", "INDICES"
        ])


# Instance globale
_asset_manager = None


def get_asset_manager(config_path: str = "config/asset_config.yaml") -> AssetManager:
    """Retourne l'instance globale du AssetManager (singleton)"""
    global _asset_manager
    if _asset_manager is None:
        _asset_manager = AssetManager(config_path)
    return _asset_manager
