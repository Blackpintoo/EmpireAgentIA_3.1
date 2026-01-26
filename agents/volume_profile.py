# agents/volume_profile.py
"""
OUTIL 1: Volume Profile & VWAP Agent (OPTIMISATION 2025-12-13)

Analyse le profil de volume pour identifier:
1. VWAP (Volume Weighted Average Price) - Prix moyen pondéré par volume
2. POC (Point of Control) - Niveau de prix avec le plus de volume
3. Value Area (VA) - Zone où 70% du volume s'est échangé
4. HVN/LVN (High/Low Volume Nodes) - Zones de support/résistance

Objectif: Améliorer la précision des niveaux SL/TP et confirmer les entrées.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

import pandas as pd
import numpy as np

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.config import get_symbol_profile
except Exception:
    def get_symbol_profile(sym: str) -> dict:
        return {}


@dataclass
class VolumeProfileParams:
    """Paramètres du Volume Profile Agent"""
    timeframe: str = "H1"
    lookback_bars: int = 100           # Nombre de bougies pour le calcul
    value_area_pct: float = 0.70       # 70% du volume pour la Value Area
    num_bins: int = 50                 # Nombre de niveaux de prix
    vwap_periods: List[str] = None     # Périodes VWAP (daily, weekly)
    hvn_threshold: float = 1.5         # Seuil HVN (>1.5x moyenne)
    lvn_threshold: float = 0.5         # Seuil LVN (<0.5x moyenne)

    def __post_init__(self):
        if self.vwap_periods is None:
            self.vwap_periods = ["session", "daily"]


class VolumeProfileAgent:
    """
    Agent d'analyse du profil de volume.

    Fournit:
    - Signal basé sur la position du prix vs VWAP/POC
    - Niveaux de support/résistance basés sur le volume
    - Confirmation des entrées via analyse volume
    """

    def __init__(
        self,
        symbol: str,
        mt5=None,
        profile: Optional[dict] = None,
        params: Optional[VolumeProfileParams] = None
    ):
        self.symbol = symbol.upper()
        self.mt5 = mt5
        self.profile = profile or get_symbol_profile(self.symbol)
        self.params = params or VolumeProfileParams()

        # Cache des calculs
        self._last_vwap: Optional[float] = None
        self._last_poc: Optional[float] = None
        self._last_vah: Optional[float] = None  # Value Area High
        self._last_val: Optional[float] = None  # Value Area Low
        self._hvn_levels: List[float] = []
        self._lvn_levels: List[float] = []

    def _get_ohlcv_data(self, timeframe: str, bars: int) -> Optional[pd.DataFrame]:
        """Récupère les données OHLCV depuis MT5"""
        if self.mt5 is None:
            return None

        try:
            # Mapping timeframe
            tf_map = {
                "M1": 1, "M5": 5, "M15": 15, "M30": 30,
                "H1": 16385, "H4": 16388, "D1": 16408
            }
            tf_val = tf_map.get(timeframe.upper(), 16385)

            rates = self.mt5.copy_rates_from_pos(self.symbol, tf_val, 0, bars)
            if rates is None or len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df

        except Exception as e:
            logger.debug(f"[VOLUME_PROFILE] Erreur récupération données: {e}")
            return None

    def calculate_vwap(self, df: pd.DataFrame) -> float:
        """
        Calcule le VWAP (Volume Weighted Average Price).
        VWAP = Somme(Prix * Volume) / Somme(Volume)
        """
        if df is None or len(df) == 0:
            return 0.0

        try:
            # Prix typique = (High + Low + Close) / 3
            typical_price = (df['high'] + df['low'] + df['close']) / 3

            # Volume (tick_volume si real_volume non dispo)
            volume = df.get('real_volume', df.get('tick_volume', pd.Series([1] * len(df))))
            if volume.sum() == 0:
                volume = pd.Series([1] * len(df))

            vwap = (typical_price * volume).sum() / volume.sum()
            return float(vwap)

        except Exception as e:
            logger.debug(f"[VOLUME_PROFILE] Erreur calcul VWAP: {e}")
            return 0.0

    def calculate_volume_profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcule le profil de volume complet.

        Returns:
            Dict avec POC, VAH, VAL, HVN, LVN
        """
        if df is None or len(df) < 10:
            return {}

        try:
            # Définir les bins de prix
            price_min = df['low'].min()
            price_max = df['high'].max()
            price_range = price_max - price_min

            if price_range <= 0:
                return {}

            bins = np.linspace(price_min, price_max, self.params.num_bins + 1)
            bin_centers = (bins[:-1] + bins[1:]) / 2

            # Calculer le volume par bin
            volume_by_bin = np.zeros(self.params.num_bins)

            for _, row in df.iterrows():
                # Volume de la bougie
                vol = row.get('real_volume', row.get('tick_volume', 1))
                if vol <= 0:
                    vol = 1

                # Distribuer le volume dans les bins traversés
                low_idx = np.searchsorted(bins, row['low']) - 1
                high_idx = np.searchsorted(bins, row['high']) - 1

                low_idx = max(0, min(low_idx, self.params.num_bins - 1))
                high_idx = max(0, min(high_idx, self.params.num_bins - 1))

                if low_idx == high_idx:
                    volume_by_bin[low_idx] += vol
                else:
                    # Distribuer uniformément
                    vol_per_bin = vol / (high_idx - low_idx + 1)
                    for i in range(low_idx, high_idx + 1):
                        volume_by_bin[i] += vol_per_bin

            total_volume = volume_by_bin.sum()
            if total_volume <= 0:
                return {}

            # POC (Point of Control) - bin avec le plus de volume
            poc_idx = np.argmax(volume_by_bin)
            poc = float(bin_centers[poc_idx])

            # Value Area (70% du volume autour du POC)
            sorted_indices = np.argsort(volume_by_bin)[::-1]
            cumulative_vol = 0
            va_indices = []

            for idx in sorted_indices:
                va_indices.append(idx)
                cumulative_vol += volume_by_bin[idx]
                if cumulative_vol >= total_volume * self.params.value_area_pct:
                    break

            va_indices = sorted(va_indices)
            vah = float(bin_centers[max(va_indices)])  # Value Area High
            val = float(bin_centers[min(va_indices)])  # Value Area Low

            # HVN et LVN
            avg_volume = volume_by_bin.mean()
            hvn_levels = []
            lvn_levels = []

            for i, vol in enumerate(volume_by_bin):
                if vol > avg_volume * self.params.hvn_threshold:
                    hvn_levels.append(float(bin_centers[i]))
                elif vol < avg_volume * self.params.lvn_threshold and vol > 0:
                    lvn_levels.append(float(bin_centers[i]))

            return {
                "poc": poc,
                "vah": vah,
                "val": val,
                "hvn_levels": hvn_levels,
                "lvn_levels": lvn_levels,
                "volume_by_bin": volume_by_bin.tolist(),
                "bin_centers": bin_centers.tolist()
            }

        except Exception as e:
            logger.debug(f"[VOLUME_PROFILE] Erreur calcul profil: {e}")
            return {}

    def get_signal(
        self,
        current_price: float,
        df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Génère un signal basé sur l'analyse du volume profile.

        Returns:
            Dict avec signal, confidence, levels, etc.
        """
        result = {
            "signal": "WAIT",
            "confidence": 0.0,
            "vwap": None,
            "poc": None,
            "vah": None,
            "val": None,
            "price_vs_vwap": None,
            "price_vs_poc": None,
            "in_value_area": False,
            "nearest_hvn": None,
            "nearest_lvn": None,
            "suggested_sl": None,
            "suggested_tp": None
        }

        # Récupérer les données si non fournies
        if df is None:
            df = self._get_ohlcv_data(self.params.timeframe, self.params.lookback_bars)

        if df is None or len(df) < 10:
            return result

        try:
            # Calculer VWAP
            vwap = self.calculate_vwap(df)
            result["vwap"] = vwap
            self._last_vwap = vwap

            # Calculer Volume Profile
            vp = self.calculate_volume_profile(df)
            if not vp:
                return result

            poc = vp["poc"]
            vah = vp["vah"]
            val = vp["val"]
            hvn_levels = vp["hvn_levels"]
            lvn_levels = vp["lvn_levels"]

            result["poc"] = poc
            result["vah"] = vah
            result["val"] = val

            self._last_poc = poc
            self._last_vah = vah
            self._last_val = val
            self._hvn_levels = hvn_levels
            self._lvn_levels = lvn_levels

            # Analyse de la position du prix
            result["price_vs_vwap"] = "above" if current_price > vwap else "below"
            result["price_vs_poc"] = "above" if current_price > poc else "below"
            result["in_value_area"] = val <= current_price <= vah

            # Trouver les niveaux HVN/LVN les plus proches
            if hvn_levels:
                hvn_above = [h for h in hvn_levels if h > current_price]
                hvn_below = [h for h in hvn_levels if h < current_price]
                if hvn_above:
                    result["nearest_hvn_above"] = min(hvn_above)
                if hvn_below:
                    result["nearest_hvn_below"] = max(hvn_below)

            if lvn_levels:
                lvn_above = [l for l in lvn_levels if l > current_price]
                lvn_below = [l for l in lvn_levels if l < current_price]
                if lvn_above:
                    result["nearest_lvn_above"] = min(lvn_above)
                if lvn_below:
                    result["nearest_lvn_below"] = max(lvn_below)

            # Génération du signal
            confidence = 0.0
            signal = "WAIT"

            # Signal LONG: Prix sous VWAP ET sous POC (potentiel retour à la moyenne)
            if current_price < vwap and current_price < poc:
                if current_price < val:  # Sous la Value Area = survente
                    signal = "LONG"
                    confidence = 0.7
                    # SL sous le prochain LVN, TP au POC
                    if lvn_levels:
                        lvn_below = [l for l in lvn_levels if l < current_price]
                        if lvn_below:
                            result["suggested_sl"] = max(lvn_below) - (vah - val) * 0.1
                    result["suggested_tp"] = poc
                else:
                    signal = "LONG"
                    confidence = 0.5
                    result["suggested_tp"] = vwap

            # Signal SHORT: Prix au-dessus VWAP ET au-dessus POC
            elif current_price > vwap and current_price > poc:
                if current_price > vah:  # Au-dessus Value Area = surachat
                    signal = "SHORT"
                    confidence = 0.7
                    # SL au-dessus prochain LVN, TP au POC
                    if lvn_levels:
                        lvn_above = [l for l in lvn_levels if l > current_price]
                        if lvn_above:
                            result["suggested_sl"] = min(lvn_above) + (vah - val) * 0.1
                    result["suggested_tp"] = poc
                else:
                    signal = "SHORT"
                    confidence = 0.5
                    result["suggested_tp"] = vwap

            # Bonus de confiance si près d'un HVN (support/résistance fort)
            for hvn in hvn_levels:
                if abs(current_price - hvn) / current_price < 0.005:  # Près d'un HVN
                    confidence += 0.15
                    break

            result["signal"] = signal
            result["confidence"] = min(confidence, 1.0)

            return result

        except Exception as e:
            logger.error(f"[VOLUME_PROFILE] Erreur génération signal: {e}")
            return result

    def analyze(self, indicators: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Interface standard pour l'orchestrateur.

        Returns:
            Dict compatible avec le système d'agents existant.
        """
        current_price = None
        if indicators:
            current_price = indicators.get("CLOSE") or indicators.get("BID") or indicators.get("PRICE")

        if current_price is None:
            return {"signal": "WAIT", "confidence": 0.0}

        result = self.get_signal(float(current_price))

        # Format compatible orchestrateur
        return {
            "signal": result["signal"],
            "confidence": result["confidence"],
            "vwap": result.get("vwap"),
            "poc": result.get("poc"),
            "vah": result.get("vah"),
            "val": result.get("val"),
            "in_value_area": result.get("in_value_area", False),
            "suggested_sl": result.get("suggested_sl"),
            "suggested_tp": result.get("suggested_tp"),
            "source": "volume_profile"
        }


# Fonction utilitaire pour créer l'agent
def create_volume_profile_agent(
    symbol: str,
    mt5=None,
    profile: Optional[dict] = None,
    params: Optional[dict] = None
) -> VolumeProfileAgent:
    """Crée une instance de VolumeProfileAgent"""
    vp_params = None
    if params:
        vp_params = VolumeProfileParams(
            timeframe=params.get("timeframe", "H1"),
            lookback_bars=params.get("lookback_bars", 100),
            value_area_pct=params.get("value_area_pct", 0.70),
            num_bins=params.get("num_bins", 50)
        )

    return VolumeProfileAgent(symbol, mt5, profile, vp_params)
