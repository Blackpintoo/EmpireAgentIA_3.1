#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SMC VISUALIZER - Visualisation graphique des patterns Smart Money Concepts
CORRECTION AUDIT #6 - 2025-12-27

Ce module génère des graphiques de debug pour visualiser les patterns SMC
détectés sur les chandeliers. Utile pour valider la détection et l'analyse.

Patterns visualisés:
- BOS (Break of Structure) - Flèches vertes/rouges
- CHoCH (Change of Character) - Triangles
- FVG (Fair Value Gaps) - Zones colorées
- Order Blocks - Rectangles
- Equal Highs/Lows - Lignes horizontales
- Inducement - Zones de piège
- Liquidity Sweeps - Marqueurs de sweep

Usage:
    from utils.smc_visualizer import visualize_patterns, SMCVisualizer

    # Visualisation simple
    visualize_patterns("BTCUSD", "H1", n_bars=100)

    # Ou avec plus de contrôle
    viz = SMCVisualizer("BTCUSD")
    fig = viz.create_chart(df, patterns)
    viz.save_chart(fig, "debug_btcusd.png")
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')  # Backend non-interactif pour serveur
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import Rectangle
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    plt = None
    mpatches = None
    Rectangle = None
    MATPLOTLIB_AVAILABLE = False

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.smc_patterns import (
        detect_bos,
        detect_choch,
        detect_fvg,
        detect_equal_highs,
        detect_equal_lows,
        detect_order_blocks,
        detect_inducement,
        detect_liquidity_sweep,
        detect_mitigation_block,
        find_pivots,
        PatternEvent,
    )
    SMC_AVAILABLE = True
except ImportError:
    SMC_AVAILABLE = False
    logger.warning("[SMC_VIZ] smc_patterns non disponible")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

DEBUG_DIR = Path("data/debug/smc")
COLORS = {
    "candle_up": "#26a69a",      # Vert
    "candle_down": "#ef5350",    # Rouge
    "bos_long": "#00ff00",       # Vert vif
    "bos_short": "#ff0000",      # Rouge vif
    "choch_long": "#00ffff",     # Cyan
    "choch_short": "#ff00ff",    # Magenta
    "fvg_long": "#90EE90",       # Vert clair
    "fvg_short": "#FFB6C1",      # Rose clair
    "order_block_long": "#228B22",  # Vert forêt
    "order_block_short": "#8B0000",  # Rouge foncé
    "equal_highs": "#FFA500",    # Orange
    "equal_lows": "#4169E1",     # Bleu royal
    "inducement": "#FFD700",     # Or
    "liquidity_sweep": "#9400D3", # Violet
    "pivot_high": "#FF6347",     # Tomate
    "pivot_low": "#4682B4",      # Bleu acier
}


# =============================================================================
# SMC VISUALIZER
# =============================================================================

class SMCVisualizer:
    """
    Génère des graphiques de visualisation pour les patterns SMC.

    Cette classe:
    1. Récupère les données OHLC depuis MT5
    2. Détecte tous les patterns SMC
    3. Génère un graphique avec annotations
    4. Sauvegarde en PNG pour analyse
    """

    def __init__(self, symbol: str, debug_dir: Optional[Path] = None):
        self.symbol = symbol.upper()
        self.debug_dir = Path(debug_dir) if debug_dir else DEBUG_DIR

        # Créer le répertoire de debug
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[SMC_VIZ] Impossible de créer {self.debug_dir}: {e}")

    def get_ohlc_data(self, timeframe: str, n_bars: int = 100) -> Optional[pd.DataFrame]:
        """Récupère les données OHLC depuis MT5."""
        if not MT5_AVAILABLE or not mt5:
            logger.warning("[SMC_VIZ] MT5 non disponible")
            return None

        try:
            tf_map = {
                "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
            }
            tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_H1)

            rates = mt5.copy_rates_from_pos(self.symbol, tf, 0, n_bars)
            if rates is None or len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df

        except Exception as e:
            logger.error(f"[SMC_VIZ] Erreur récupération données: {e}")
            return None

    def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, List[PatternEvent]]:
        """Détecte tous les patterns SMC sur les données."""
        if not SMC_AVAILABLE:
            return {}

        patterns = {}

        try:
            # Pivots (utilisés par plusieurs patterns)
            pivots = find_pivots(df)

            # Patterns de structure
            patterns["bos"] = detect_bos(df, pivots=pivots)
            patterns["choch"] = detect_choch(df, pivots=pivots)

            # Imbalances
            patterns["fvg"] = detect_fvg(df)

            # Zones
            patterns["order_blocks"] = detect_order_blocks(df, pivots=pivots)
            patterns["equal_highs"] = detect_equal_highs(df)
            patterns["equal_lows"] = detect_equal_lows(df)

            # Nouveaux patterns Phase 2
            patterns["inducement"] = detect_inducement(df, pivots=pivots)
            patterns["liquidity_sweep"] = detect_liquidity_sweep(df)
            patterns["mitigation_block"] = detect_mitigation_block(df, pivots=pivots)

            # Stocker les pivots aussi
            patterns["_pivots"] = pivots

        except Exception as e:
            logger.error(f"[SMC_VIZ] Erreur détection patterns: {e}")

        return patterns

    def create_chart(
        self,
        df: pd.DataFrame,
        patterns: Dict[str, List],
        title: Optional[str] = None
    ) -> Optional[Any]:
        """
        Crée un graphique matplotlib avec les patterns annotés.

        Args:
            df: DataFrame OHLC
            patterns: Dict des patterns détectés
            title: Titre du graphique

        Returns:
            Figure matplotlib ou None si erreur
        """
        if not MATPLOTLIB_AVAILABLE:
            logger.error("[SMC_VIZ] Matplotlib non disponible")
            return None

        try:
            fig, ax = plt.subplots(figsize=(16, 10))

            # Titre
            if title:
                ax.set_title(title, fontsize=14, fontweight='bold')
            else:
                ax.set_title(f"{self.symbol} - SMC Patterns Analysis", fontsize=14, fontweight='bold')

            # 1. Dessiner les chandeliers
            self._draw_candlesticks(ax, df)

            # 2. Dessiner les pivots
            pivots = patterns.get("_pivots", [])
            self._draw_pivots(ax, df, pivots)

            # 3. Dessiner les patterns
            self._draw_bos_choch(ax, df, patterns.get("bos", []), patterns.get("choch", []))
            self._draw_fvg(ax, df, patterns.get("fvg", []))
            self._draw_order_blocks(ax, df, patterns.get("order_blocks", []))
            self._draw_equal_levels(ax, df, patterns.get("equal_highs", []), patterns.get("equal_lows", []))
            self._draw_inducement(ax, df, patterns.get("inducement", []))
            self._draw_liquidity_sweep(ax, df, patterns.get("liquidity_sweep", []))

            # 4. Légende
            self._add_legend(ax, patterns)

            # Formattage
            ax.set_xlabel("Barre")
            ax.set_ylabel("Prix")
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            return fig

        except Exception as e:
            logger.error(f"[SMC_VIZ] Erreur création graphique: {e}")
            return None

    def _draw_candlesticks(self, ax: Any, df: pd.DataFrame) -> None:
        """Dessine les chandeliers."""
        for i in range(len(df)):
            open_price = df['open'].iloc[i]
            close_price = df['close'].iloc[i]
            high_price = df['high'].iloc[i]
            low_price = df['low'].iloc[i]

            color = COLORS["candle_up"] if close_price >= open_price else COLORS["candle_down"]

            # Corps
            body_bottom = min(open_price, close_price)
            body_height = abs(close_price - open_price)
            ax.add_patch(Rectangle(
                (i - 0.3, body_bottom), 0.6, body_height,
                facecolor=color, edgecolor='black', linewidth=0.5
            ))

            # Mèches
            ax.plot([i, i], [low_price, body_bottom], color='black', linewidth=0.5)
            ax.plot([i, i], [body_bottom + body_height, high_price], color='black', linewidth=0.5)

    def _draw_pivots(self, ax: Any, df: pd.DataFrame, pivots: List) -> None:
        """Dessine les pivots (swing highs/lows)."""
        for idx, price, pivot_type in pivots:
            if idx >= len(df):
                continue

            if pivot_type == "high":
                ax.scatter(idx, price, marker='v', color=COLORS["pivot_high"], s=50, zorder=5)
            else:
                ax.scatter(idx, price, marker='^', color=COLORS["pivot_low"], s=50, zorder=5)

    def _draw_bos_choch(self, ax: Any, df: pd.DataFrame, bos_events: List, choch_events: List) -> None:
        """Dessine les BOS et CHoCH."""
        # BOS
        for event in bos_events:
            if event.start_idx >= len(df):
                continue

            color = COLORS["bos_long"] if event.direction == "LONG" else COLORS["bos_short"]
            ax.axhline(y=event.level, color=color, linestyle='--', alpha=0.7, linewidth=1)
            ax.annotate(
                f"BOS {event.direction}",
                xy=(event.start_idx, event.level),
                fontsize=8,
                color=color,
                fontweight='bold'
            )

        # CHoCH
        for event in choch_events:
            if event.start_idx >= len(df):
                continue

            color = COLORS["choch_long"] if event.direction == "LONG" else COLORS["choch_short"]
            ax.axhline(y=event.level, color=color, linestyle=':', alpha=0.7, linewidth=1.5)
            ax.annotate(
                f"CHoCH {event.direction}",
                xy=(event.start_idx, event.level),
                fontsize=8,
                color=color,
                fontweight='bold'
            )

    def _draw_fvg(self, ax: Any, df: pd.DataFrame, fvg_events: List) -> None:
        """Dessine les Fair Value Gaps."""
        for event in fvg_events:
            if event.start_idx >= len(df):
                continue

            color = COLORS["fvg_long"] if event.direction == "LONG" else COLORS["fvg_short"]
            gap_low = event.meta.get("gap_low", event.level - 1)
            gap_high = event.meta.get("gap_high", event.level + 1)

            # Rectangle pour le gap
            width = (event.end_idx - event.start_idx) if event.end_idx else 3
            ax.add_patch(Rectangle(
                (event.start_idx, gap_low),
                width,
                gap_high - gap_low,
                facecolor=color,
                alpha=0.3,
                edgecolor=color,
                linewidth=1
            ))

    def _draw_order_blocks(self, ax: Any, df: pd.DataFrame, ob_events: List) -> None:
        """Dessine les Order Blocks."""
        for event in ob_events:
            if event.start_idx >= len(df):
                continue

            color = COLORS["order_block_long"] if event.direction == "LONG" else COLORS["order_block_short"]
            zone_low = event.meta.get("zone_low", event.level - 1)
            zone_high = event.meta.get("zone_high", event.level + 1)

            # Rectangle pour l'OB (s'étend jusqu'à la fin)
            width = len(df) - event.start_idx
            ax.add_patch(Rectangle(
                (event.start_idx, zone_low),
                width,
                zone_high - zone_low,
                facecolor=color,
                alpha=0.2,
                edgecolor=color,
                linewidth=1,
                linestyle='--'
            ))
            ax.annotate(
                f"OB",
                xy=(event.start_idx, zone_high),
                fontsize=7,
                color=color,
                fontweight='bold'
            )

    def _draw_equal_levels(self, ax: Any, df: pd.DataFrame, eqh_events: List, eql_events: List) -> None:
        """Dessine les Equal Highs/Lows."""
        # Equal Highs
        for event in eqh_events:
            ax.axhline(y=event.level, color=COLORS["equal_highs"], linestyle='-', alpha=0.5, linewidth=2)
            ax.annotate(
                f"EQH (x{event.meta.get('count', 2)})",
                xy=(len(df) - 5, event.level),
                fontsize=7,
                color=COLORS["equal_highs"]
            )

        # Equal Lows
        for event in eql_events:
            ax.axhline(y=event.level, color=COLORS["equal_lows"], linestyle='-', alpha=0.5, linewidth=2)
            ax.annotate(
                f"EQL (x{event.meta.get('count', 2)})",
                xy=(len(df) - 5, event.level),
                fontsize=7,
                color=COLORS["equal_lows"]
            )

    def _draw_inducement(self, ax: Any, df: pd.DataFrame, events: List) -> None:
        """Dessine les Inducements."""
        for event in events:
            if event.start_idx >= len(df):
                continue

            ax.scatter(
                event.start_idx,
                event.level,
                marker='*',
                color=COLORS["inducement"],
                s=200,
                zorder=10,
                edgecolors='black',
                linewidths=0.5
            )
            ax.annotate(
                f"IND {event.direction}",
                xy=(event.start_idx, event.level),
                xytext=(5, 10),
                textcoords='offset points',
                fontsize=8,
                color=COLORS["inducement"],
                fontweight='bold'
            )

    def _draw_liquidity_sweep(self, ax: Any, df: pd.DataFrame, events: List) -> None:
        """Dessine les Liquidity Sweeps."""
        for event in events:
            if event.start_idx >= len(df):
                continue

            ax.scatter(
                event.start_idx,
                event.level,
                marker='X',
                color=COLORS["liquidity_sweep"],
                s=150,
                zorder=10,
                edgecolors='black',
                linewidths=0.5
            )

    def _add_legend(self, ax: Any, patterns: Dict) -> None:
        """Ajoute une légende avec le compte des patterns."""
        legend_items = []

        counts = {
            "BOS": len(patterns.get("bos", [])),
            "CHoCH": len(patterns.get("choch", [])),
            "FVG": len(patterns.get("fvg", [])),
            "Order Blocks": len(patterns.get("order_blocks", [])),
            "Equal H/L": len(patterns.get("equal_highs", [])) + len(patterns.get("equal_lows", [])),
            "Inducement": len(patterns.get("inducement", [])),
            "Liq. Sweep": len(patterns.get("liquidity_sweep", [])),
        }

        legend_text = "Patterns: " + " | ".join([f"{k}: {v}" for k, v in counts.items() if v > 0])
        ax.text(
            0.02, 0.98, legend_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        )

    def save_chart(self, fig: Any, filename: Optional[str] = None) -> Optional[Path]:
        """
        Sauvegarde le graphique en PNG.

        Args:
            fig: Figure matplotlib
            filename: Nom du fichier (auto-généré si None)

        Returns:
            Path du fichier sauvegardé
        """
        if fig is None:
            return None

        try:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.symbol}_{timestamp}.png"

            filepath = self.debug_dir / filename
            fig.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close(fig)

            logger.info(f"[SMC_VIZ] Graphique sauvegardé: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[SMC_VIZ] Erreur sauvegarde: {e}")
            return None

    def visualize(self, timeframe: str = "H1", n_bars: int = 100) -> Optional[Path]:
        """
        Génère et sauvegarde une visualisation complète.

        Args:
            timeframe: Timeframe à analyser
            n_bars: Nombre de barres

        Returns:
            Path du fichier PNG sauvegardé
        """
        # Récupérer les données
        df = self.get_ohlc_data(timeframe, n_bars)
        if df is None:
            logger.warning(f"[SMC_VIZ] Pas de données pour {self.symbol} {timeframe}")
            return None

        # Détecter les patterns
        patterns = self.detect_all_patterns(df)

        # Créer le graphique
        title = f"{self.symbol} {timeframe} - SMC Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        fig = self.create_chart(df, patterns, title)

        if fig is None:
            return None

        # Sauvegarder
        filename = f"{self.symbol}_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        return self.save_chart(fig, filename)


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def visualize_patterns(
    symbol: str,
    timeframe: str = "H1",
    n_bars: int = 100,
    debug_dir: Optional[str] = None
) -> Optional[Path]:
    """
    Fonction utilitaire pour visualiser rapidement les patterns SMC.

    Args:
        symbol: Symbole à analyser
        timeframe: Timeframe (M1, M5, M15, M30, H1, H4, D1)
        n_bars: Nombre de barres à analyser
        debug_dir: Répertoire de sauvegarde (optionnel)

    Returns:
        Path du fichier PNG généré

    Usage:
        from utils.smc_visualizer import visualize_patterns
        path = visualize_patterns("BTCUSD", "H1", 100)
        print(f"Graphique sauvegardé: {path}")
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.error("[SMC_VIZ] Matplotlib requis pour la visualisation")
        return None

    viz = SMCVisualizer(symbol, debug_dir=Path(debug_dir) if debug_dir else None)
    return viz.visualize(timeframe, n_bars)


def visualize_from_dataframe(
    symbol: str,
    df: pd.DataFrame,
    output_path: Optional[str] = None
) -> Optional[Path]:
    """
    Visualise les patterns SMC à partir d'un DataFrame existant.

    Args:
        symbol: Symbole (pour le titre)
        df: DataFrame avec colonnes open, high, low, close
        output_path: Chemin de sortie (optionnel)

    Returns:
        Path du fichier PNG
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.error("[SMC_VIZ] Matplotlib requis pour la visualisation")
        return None

    viz = SMCVisualizer(symbol)
    patterns = viz.detect_all_patterns(df)
    fig = viz.create_chart(df, patterns)

    if fig is None:
        return None

    if output_path:
        return viz.save_chart(fig, output_path)
    else:
        return viz.save_chart(fig)


__all__ = [
    "SMCVisualizer",
    "visualize_patterns",
    "visualize_from_dataframe",
    "COLORS",
    "DEBUG_DIR",
]
