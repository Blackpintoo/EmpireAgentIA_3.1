# utils/smc_patterns.py
"""
Détecteurs légers pour Smart Money Concepts (SMC).

Les fonctions reposent sur des heuristiques simples adaptées à un flux OHLC
restreint (DataFrame Pandas contenant au minimum `open`, `high`, `low`, `close`).
Elles retournent des événements structurés via `PatternEvent`, ce qui permet aux
agents de combiner ces signaux sans recréer la logique côté orchestrateur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "PatternEvent",
    "find_pivots",
    "detect_bos",
    "detect_choch",
    "detect_fvg",
    "detect_equal_highs",
    "detect_equal_lows",
    "detect_order_blocks",
    "detect_breaker_blocks",
    "detect_inducement",
    "detect_liquidity_sweep",
    "detect_mitigation_block",
    "compute_equilibrium",
    "compute_ote_zone",
    "compute_invalidation_sl",
]


@dataclass
class PatternEvent:
    """Représente une occurrence de pattern SMC détectée."""

    pattern: str
    direction: Optional[str]
    level: float
    start_idx: int
    end_idx: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'événement en dictionnaire pour sérialisation JSON."""
        return {
            "pattern": self.pattern,
            "direction": self.direction,
            "level": self.level,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "meta": self.meta,
        }


def _validate_df(df: pd.DataFrame) -> None:
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes OHLC manquantes: {sorted(missing)}")
    if df.empty:
        raise ValueError("DataFrame vide")


def find_pivots(
    df: pd.DataFrame,
    window: int = 3,
    *,
    use_wicks: bool = True,
) -> List[Tuple[int, float, str]]:
    """
    Retourne une liste de pivots (index, prix, type 'high'/'low').

    Args:
        df: DataFrame OHLC.
        window: nombre de barres de part et d'autre pour confirmer un pivot.
        use_wicks: True => pivots sur high/low, False => pivots sur close.
    """
    _validate_df(df)
    if window < 1:
        raise ValueError("window doit être >= 1")

    highs = df["high"] if use_wicks else df["close"]
    lows = df["low"] if use_wicks else df["close"]
    pivots: List[Tuple[int, float, str]] = []
    for idx in range(window, len(df) - window):
        segment = highs.iloc[idx - window : idx + window + 1]
        if highs.iloc[idx] == segment.max():
            pivots.append((idx, float(highs.iloc[idx]), "high"))
            continue
        segment = lows.iloc[idx - window : idx + window + 1]
        if lows.iloc[idx] == segment.min():
            pivots.append((idx, float(lows.iloc[idx]), "low"))
    return pivots


def _latest_pivots(
    pivots: Iterable[Tuple[int, float, str]],
    pivot_type: str,
    n: int,
) -> List[Tuple[int, float]]:
    filtered = [(idx, price) for idx, price, typ in pivots if typ == pivot_type]
    return filtered[-n:]


def detect_bos(
    df: pd.DataFrame,
    *,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
    tolerance: float = 1e-4,
) -> List[PatternEvent]:
    """
    Détecte Break Of Structure (BOS) haussiers/baissiers sur les derniers pivots.
    """
    _validate_df(df)
    pivots = pivots or find_pivots(df)
    events: List[PatternEvent] = []
    if len(pivots) < 3:
        return events

    close = float(df["close"].iloc[-1])
    highs = _latest_pivots(pivots, "high", 2)
    lows = _latest_pivots(pivots, "low", 2)

    if len(highs) >= 1 and close > highs[-1][1] + tolerance:
        idx, price = highs[-1]
        events.append(
            PatternEvent(
                pattern="BOS",
                direction="LONG",
                level=price,
                start_idx=idx,
                meta={"broken_high": price},
            )
        )

    if len(lows) >= 1 and close < lows[-1][1] - tolerance:
        idx, price = lows[-1]
        events.append(
            PatternEvent(
                pattern="BOS",
                direction="SHORT",
                level=price,
                start_idx=idx,
                meta={"broken_low": price},
            )
        )
    return events


def detect_choch(
    df: pd.DataFrame,
    *,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
    tolerance: float = 1e-4,
) -> List[PatternEvent]:
    """
    Change of Character : rupture du dernier swing opposé.
    """
    _validate_df(df)
    pivots = pivots or find_pivots(df)
    events: List[PatternEvent] = []
    if len(pivots) < 4:
        return events

    close = float(df["close"].iloc[-1])
    highs = _latest_pivots(pivots, "high", 2)
    lows = _latest_pivots(pivots, "low", 2)
    if len(highs) < 1 or len(lows) < 1:
        return events

    last_pivot = pivots[-1]
    if last_pivot[2] == "high":
        # tendance haussière -> CHoCH si cassure du dernier plus bas
        low_idx, low_price = lows[-1]
        if close < low_price - tolerance:
            events.append(
                PatternEvent(
                    pattern="CHoCH",
                    direction="SHORT",
                    level=low_price,
                    start_idx=low_idx,
                    meta={"broken_low": low_price},
                )
            )
    else:
        high_idx, high_price = highs[-1]
        if close > high_price + tolerance:
            events.append(
                PatternEvent(
                    pattern="CHoCH",
                    direction="LONG",
                    level=high_price,
                    start_idx=high_idx,
                    meta={"broken_high": high_price},
                )
            )
    return events


def detect_fvg(
    df: pd.DataFrame,
    lookback: int = 10,
    *,
    tolerance: float = 0.0,
) -> List[PatternEvent]:
    """
    Détecte les Fair Value Gaps / Imbalances sur les trois dernières bougies.
    """
    _validate_df(df)
    events: List[PatternEvent] = []
    if len(df) < 3:
        return events

    start = max(2, len(df) - lookback)
    for idx in range(start, len(df)):
        if idx < 2:
            continue
        high_prev = float(df["high"].iloc[idx - 2])
        low_prev = float(df["low"].iloc[idx - 2])
        high_cur = float(df["high"].iloc[idx])
        low_cur = float(df["low"].iloc[idx])
        mid = idx - 1
        low_mid = float(df["low"].iloc[mid])
        high_mid = float(df["high"].iloc[mid])

        if low_mid > high_prev + tolerance:
            events.append(
                PatternEvent(
                    pattern="FVG",
                    direction="LONG",
                    level=(high_prev + low_mid) / 2.0,
                    start_idx=idx - 2,
                    end_idx=idx,
                    meta={
                        "gap_high": low_mid,
                        "gap_low": high_prev,
                        "width": low_mid - high_prev,
                    },
                )
            )
        if high_mid < low_prev - tolerance:
            events.append(
                PatternEvent(
                    pattern="FVG",
                    direction="SHORT",
                    level=(low_prev + high_mid) / 2.0,
                    start_idx=idx - 2,
                    end_idx=idx,
                    meta={
                        "gap_high": low_prev,
                        "gap_low": high_mid,
                        "width": low_prev - high_mid,
                    },
                )
            )
    return events


def detect_equal_highs(
    df: pd.DataFrame,
    lookback: int = 20,
    *,
    tolerance: float = 1e-3,
) -> List[PatternEvent]:
    """
    Cherche des equal highs (liquidité au-dessus) dans la fenêtre `lookback`.
    """
    _validate_df(df)
    highs = df["high"].tail(lookback)
    events: List[PatternEvent] = []
    if len(highs) < 2:
        return events
    max_idx = int(highs.idxmax())
    near = highs[(np.abs(highs - highs.max()) <= tolerance)]
    if len(near) >= 2:
        events.append(
            PatternEvent(
                pattern="EQH",
                direction="SHORT",
                level=float(highs.max()),
                start_idx=int(near.index.min()),
                end_idx=max_idx,
                meta={"count": len(near)},
            )
        )
    return events


def detect_equal_lows(
    df: pd.DataFrame,
    lookback: int = 20,
    *,
    tolerance: float = 1e-3,
) -> List[PatternEvent]:
    """
    Cherche des equal lows (liquidité en dessous) dans la fenêtre `lookback`.
    """
    _validate_df(df)
    lows = df["low"].tail(lookback)
    events: List[PatternEvent] = []
    if len(lows) < 2:
        return events
    min_idx = int(lows.idxmin())
    near = lows[(np.abs(lows - lows.min()) <= tolerance)]
    if len(near) >= 2:
        events.append(
            PatternEvent(
                pattern="EQL",
                direction="LONG",
                level=float(lows.min()),
                start_idx=int(near.index.min()),
                end_idx=min_idx,
                meta={"count": len(near)},
            )
        )
    return events


def detect_order_blocks(
    df: pd.DataFrame,
    *,
    lookback: int = 30,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
) -> List[PatternEvent]:
    """
    Identifie les dernières bougies d'impulsion (bullish/bearish) précédant une cassure.
    """
    _validate_df(df)
    pivots = pivots or find_pivots(df)
    events: List[PatternEvent] = []
    if not pivots:
        return events

    recent = df.tail(lookback)
    closes = recent["close"]
    highs = recent["high"]
    lows = recent["low"]

    if len(closes) < 3:
        return events

    close_last = float(closes.iloc[-1])
    high_last = float(highs.max())
    low_last = float(lows.min())

    # Bullish order block : dernière bougie baissière avant cassure haussière
    if close_last > high_last * 0.999:
        mask = recent["close"] < recent["open"]
        bearish_candles = recent[mask]
        if not bearish_candles.empty:
            candle = bearish_candles.iloc[-1]
            idx = int(candle.name)
            events.append(
                PatternEvent(
                    pattern="ORDER_BLOCK",
                    direction="LONG",
                    level=float(candle["open"]),
                    start_idx=idx,
                    meta={
                        "zone_low": float(min(candle["open"], candle["close"])),
                        "zone_high": float(max(candle["open"], candle["close"])),
                    },
                )
            )

    # Bearish order block : inverse
    if close_last < low_last * 1.001:
        mask = recent["close"] > recent["open"]
        bullish_candles = recent[mask]
        if not bullish_candles.empty:
            candle = bullish_candles.iloc[-1]
            idx = int(candle.name)
            events.append(
                PatternEvent(
                    pattern="ORDER_BLOCK",
                    direction="SHORT",
                    level=float(candle["open"]),
                    start_idx=idx,
                    meta={
                        "zone_low": float(min(candle["open"], candle["close"])),
                        "zone_high": float(max(candle["open"], candle["close"])),
                    },
                )
            )

    return events


def detect_breaker_blocks(
    df: pd.DataFrame,
    *,
    tolerance: float = 1e-4,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
) -> List[PatternEvent]:
    """
    Détection heuristique des breaker blocks :
    un order block invalidé qui redevient zone d'intérêt après cassure inverse.
    """
    pivots = pivots or find_pivots(df)
    if len(pivots) < 3:
        return []
    order_blocks = detect_order_blocks(df, pivots=pivots)
    if not order_blocks:
        return []

    close = float(df["close"].iloc[-1])
    events: List[PatternEvent] = []
    for ob in order_blocks:
        zone_low = ob.meta.get("zone_low", ob.level)
        zone_high = ob.meta.get("zone_high", ob.level)
        if ob.direction == "LONG":
            # invalidation si close < zone_low, puis retour au-dessus => breaker
            if close > zone_high + tolerance:
                events.append(
                    PatternEvent(
                        pattern="BREAKER_BLOCK",
                        direction="LONG",
                        level=zone_high,
                        start_idx=ob.start_idx,
                        meta={"from_ob": ob},
                    )
                )
        else:
            if close < zone_low - tolerance:
                events.append(
                    PatternEvent(
                        pattern="BREAKER_BLOCK",
                        direction="SHORT",
                        level=zone_low,
                        start_idx=ob.start_idx,
                        meta={"from_ob": ob},
                    )
                )
    return events


def compute_equilibrium(
    df: pd.DataFrame,
    lookback: int = 30,
) -> Dict[str, float]:
    """
    Renvoie le midpoint (équilibre) du dernier range HL / LL.
    """
    _validate_df(df)
    segment = df.tail(lookback)
    high = float(segment["high"].max())
    low = float(segment["low"].min())
    midpoint = (high + low) / 2.0
    return {"high": high, "low": low, "equilibrium": midpoint}


def compute_ote_zone(
    df: pd.DataFrame,
    *,
    swing_high: Optional[float] = None,
    swing_low: Optional[float] = None,
    lookback: int = 100,
) -> Optional[Tuple[float, float]]:
    """
    OTE (Optimal Trade Entry) : zone 62%-79% du dernier swing.
    """
    _validate_df(df)
    segment = df.tail(lookback)
    swing_high = swing_high or float(segment["high"].max())
    swing_low = swing_low or float(segment["low"].min())
    if swing_high <= swing_low:
        return None
    range_ = swing_high - swing_low
    zone_low = swing_high - 0.79 * range_
    zone_high = swing_high - 0.62 * range_
    return (zone_low, zone_high)


# =============================================================================
# NOUVELLES FONCTIONS SMC - PHASE 2 (2025-12-25)
# =============================================================================

def detect_inducement(
    df: pd.DataFrame,
    *,
    lookback: int = 30,
    tolerance: float = 0.001,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
) -> List[PatternEvent]:
    """
    Detecte les pieges de liquidite (Inducement).

    L'inducement est un faux breakout qui attire les traders retail avant
    un mouvement inverse. Il se produit quand:
    - Le prix casse legerement au-dessus d'equal highs puis revient
    - Le prix casse legerement en-dessous d'equal lows puis revient

    C'est un signal de reversal puissant car il indique que la smart money
    a collecte la liquidite et va maintenant pousser dans l'autre direction.

    Args:
        df: DataFrame OHLC
        lookback: Nombre de barres a analyser
        tolerance: Tolerance pour detecter les equal highs/lows (en %)
        pivots: Liste de pivots pre-calcules (optionnel)

    Returns:
        Liste de PatternEvent avec pattern="INDUCEMENT"
    """
    _validate_df(df)
    events: List[PatternEvent] = []

    if len(df) < lookback:
        return events

    segment = df.tail(lookback)
    current_close = float(segment["close"].iloc[-1])
    current_high = float(segment["high"].iloc[-1])
    current_low = float(segment["low"].iloc[-1])

    # Trouver les equal highs/lows dans la fenetre
    highs = segment["high"].iloc[:-3]  # Exclure les 3 dernieres barres
    lows = segment["low"].iloc[:-3]

    if len(highs) < 2:
        return events

    # Calculer les niveaux de liquidite (equal highs/lows)
    max_high = float(highs.max())
    min_low = float(lows.min())

    # Tolerance en valeur absolue
    tol_high = max_high * tolerance
    tol_low = min_low * tolerance

    # Compter les touches proches du max/min
    near_highs = highs[abs(highs - max_high) <= tol_high]
    near_lows = lows[abs(lows - min_low) <= tol_low]

    # Inducement LONG: prix a balaye les equal lows puis est revenu au-dessus
    if len(near_lows) >= 2:
        # Verifier si une meche recente a perce le niveau
        recent_low = float(segment["low"].iloc[-2])  # Avant-derniere bougie
        sweep_occurred = recent_low < (min_low - tol_low)
        price_recovered = current_close > min_low

        if sweep_occurred and price_recovered:
            events.append(
                PatternEvent(
                    pattern="INDUCEMENT",
                    direction="LONG",
                    level=min_low,
                    start_idx=int(segment.index[-2]),
                    end_idx=int(segment.index[-1]),
                    meta={
                        "liquidity_level": min_low,
                        "sweep_low": recent_low,
                        "recovery_close": current_close,
                        "touches": len(near_lows),
                        "strength": len(near_lows) / 2.0,  # Plus de touches = plus fort
                    },
                )
            )

    # Inducement SHORT: prix a balaye les equal highs puis est revenu en-dessous
    if len(near_highs) >= 2:
        recent_high = float(segment["high"].iloc[-2])
        sweep_occurred = recent_high > (max_high + tol_high)
        price_recovered = current_close < max_high

        if sweep_occurred and price_recovered:
            events.append(
                PatternEvent(
                    pattern="INDUCEMENT",
                    direction="SHORT",
                    level=max_high,
                    start_idx=int(segment.index[-2]),
                    end_idx=int(segment.index[-1]),
                    meta={
                        "liquidity_level": max_high,
                        "sweep_high": recent_high,
                        "recovery_close": current_close,
                        "touches": len(near_highs),
                        "strength": len(near_highs) / 2.0,
                    },
                )
            )

    return events


def detect_liquidity_sweep(
    df: pd.DataFrame,
    *,
    lookback: int = 20,
    min_sweep_pct: float = 0.001,
    min_recovery_pct: float = 0.3,
) -> List[PatternEvent]:
    """
    Detecte les liquidity sweeps (balayages de liquidite).

    Un sweep est confirme quand:
    1. Le prix depasse un niveau de liquidite (equal highs/lows ou pivot)
    2. Puis revient dans la direction opposee rapidement

    Args:
        df: DataFrame OHLC
        lookback: Fenetre d'analyse
        min_sweep_pct: Pourcentage minimum de depassement pour considerer un sweep
        min_recovery_pct: Pourcentage de recovery du range pour confirmer

    Returns:
        Liste de PatternEvent avec pattern="LIQUIDITY_SWEEP"
    """
    _validate_df(df)
    events: List[PatternEvent] = []

    if len(df) < 5:
        return events

    segment = df.tail(lookback)

    # Analyser les 3 dernieres bougies
    for i in range(-3, -1):
        if abs(i) > len(segment):
            continue

        candle = segment.iloc[i]
        next_candle = segment.iloc[i + 1] if i < -1 else segment.iloc[-1]

        candle_range = float(candle["high"] - candle["low"])
        if candle_range == 0:
            continue

        # Sweep haussier (faux breakout vers le haut)
        upper_wick = float(candle["high"] - max(candle["open"], candle["close"]))
        lower_wick = float(min(candle["open"], candle["close"]) - candle["low"])

        # Grande meche haute avec cloture basse = sweep des highs
        if upper_wick > candle_range * 0.4:
            next_close = float(next_candle["close"])
            if next_close < float(candle["open"]):
                events.append(
                    PatternEvent(
                        pattern="LIQUIDITY_SWEEP",
                        direction="SHORT",
                        level=float(candle["high"]),
                        start_idx=int(candle.name),
                        meta={
                            "sweep_type": "high_sweep",
                            "wick_ratio": upper_wick / candle_range,
                            "confirmation": "bearish_close",
                        },
                    )
                )

        # Grande meche basse avec cloture haute = sweep des lows
        if lower_wick > candle_range * 0.4:
            next_close = float(next_candle["close"])
            if next_close > float(candle["open"]):
                events.append(
                    PatternEvent(
                        pattern="LIQUIDITY_SWEEP",
                        direction="LONG",
                        level=float(candle["low"]),
                        start_idx=int(candle.name),
                        meta={
                            "sweep_type": "low_sweep",
                            "wick_ratio": lower_wick / candle_range,
                            "confirmation": "bullish_close",
                        },
                    )
                )

    return events


def detect_mitigation_block(
    df: pd.DataFrame,
    *,
    lookback: int = 50,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
) -> List[PatternEvent]:
    """
    Detecte les Mitigation Blocks - zones ou la smart money a laisse des ordres.

    Un mitigation block est un order block qui:
    1. A ete partiellement teste (le prix est revenu dans la zone)
    2. Mais n'a pas ete completement invalide
    3. Devient une zone d'entree privilegiee

    Difference avec Order Block:
    - OB: zone jamais retestee
    - Mitigation: zone testee mais tenue

    Args:
        df: DataFrame OHLC
        lookback: Fenetre d'analyse
        pivots: Pivots pre-calcules

    Returns:
        Liste de PatternEvent avec pattern="MITIGATION_BLOCK"
    """
    _validate_df(df)
    events: List[PatternEvent] = []

    if len(df) < 10:
        return events

    # D'abord trouver les order blocks
    order_blocks = detect_order_blocks(df, lookback=lookback, pivots=pivots)

    if not order_blocks:
        return events

    current_close = float(df["close"].iloc[-1])
    current_low = float(df["low"].iloc[-1])
    current_high = float(df["high"].iloc[-1])

    for ob in order_blocks:
        zone_low = ob.meta.get("zone_low", ob.level)
        zone_high = ob.meta.get("zone_high", ob.level)
        ob_idx = ob.start_idx

        # Verifier si la zone a ete testee depuis sa creation
        if ob_idx >= len(df) - 3:
            continue

        # Regarder les barres apres l'OB
        post_ob = df.iloc[ob_idx + 1:]
        if len(post_ob) < 3:
            continue

        # Pour un OB bullish (LONG), verifier si le prix est revenu dans la zone
        if ob.direction == "LONG":
            # Le prix doit avoir touche la zone puis rebondi
            touched = (post_ob["low"] <= zone_high).any()
            held = (post_ob["close"] > zone_low).all()

            if touched and held:
                # C'est un mitigation block valide - zone d'entree LONG
                # Verifier si on est proche de la zone maintenant
                in_zone = zone_low <= current_close <= zone_high * 1.01
                near_zone = zone_low * 0.99 <= current_low <= zone_high * 1.02

                if in_zone or near_zone:
                    events.append(
                        PatternEvent(
                            pattern="MITIGATION_BLOCK",
                            direction="LONG",
                            level=zone_low,
                            start_idx=ob_idx,
                            end_idx=int(df.index[-1]),
                            meta={
                                "zone_low": zone_low,
                                "zone_high": zone_high,
                                "entry_zone": True,
                                "times_tested": int((post_ob["low"] <= zone_high).sum()),
                                "strength": "high" if held else "medium",
                            },
                        )
                    )

        elif ob.direction == "SHORT":
            touched = (post_ob["high"] >= zone_low).any()
            held = (post_ob["close"] < zone_high).all()

            if touched and held:
                in_zone = zone_low * 0.99 <= current_close <= zone_high
                near_zone = zone_low * 0.98 <= current_high <= zone_high * 1.01

                if in_zone or near_zone:
                    events.append(
                        PatternEvent(
                            pattern="MITIGATION_BLOCK",
                            direction="SHORT",
                            level=zone_high,
                            start_idx=ob_idx,
                            end_idx=int(df.index[-1]),
                            meta={
                                "zone_low": zone_low,
                                "zone_high": zone_high,
                                "entry_zone": True,
                                "times_tested": int((post_ob["high"] >= zone_low).sum()),
                                "strength": "high" if held else "medium",
                            },
                        )
                    )

    return events


def compute_invalidation_sl(
    df: pd.DataFrame,
    direction: str,
    *,
    lookback: int = 50,
    buffer_pct: float = 0.001,
    pivots: Optional[List[Tuple[int, float, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Calcule le Stop Loss base sur l'invalidation de structure SMC.

    Pour un trade LONG:
    - SL = sous le dernier Higher Low (HL) significatif
    - Si pas de HL, sous le dernier swing low

    Pour un trade SHORT:
    - SL = au-dessus du dernier Lower High (LH) significatif
    - Si pas de LH, au-dessus du dernier swing high

    Args:
        df: DataFrame OHLC
        direction: "LONG" ou "SHORT"
        lookback: Fenetre d'analyse
        buffer_pct: Buffer additionnel en pourcentage
        pivots: Pivots pre-calcules

    Returns:
        Dict avec sl_price, sl_type, distance_pct, invalidation_level
    """
    _validate_df(df)

    if direction not in ("LONG", "SHORT"):
        return None

    pivots = pivots or find_pivots(df.tail(lookback))

    if len(pivots) < 2:
        # Fallback: utiliser le min/max recent
        segment = df.tail(lookback)
        if direction == "LONG":
            sl_price = float(segment["low"].min())
        else:
            sl_price = float(segment["high"].max())

        current = float(df["close"].iloc[-1])
        buffer = current * buffer_pct

        if direction == "LONG":
            sl_price -= buffer
        else:
            sl_price += buffer

        distance_pct = abs(current - sl_price) / current * 100

        return {
            "sl_price": sl_price,
            "sl_type": "range_extremum",
            "distance_pct": distance_pct,
            "invalidation_level": sl_price,
        }

    current = float(df["close"].iloc[-1])

    if direction == "LONG":
        # Trouver le dernier swing low (HL dans une tendance haussiere)
        lows = [(idx, price) for idx, price, typ in pivots if typ == "low"]
        if not lows:
            return None

        # Prendre le plus recent
        last_low_idx, last_low_price = lows[-1]

        # Verifier si c'est un HL (higher low)
        is_hl = True
        if len(lows) >= 2:
            prev_low_price = lows[-2][1]
            is_hl = last_low_price > prev_low_price

        # SL juste sous ce niveau
        buffer = last_low_price * buffer_pct
        sl_price = last_low_price - buffer

        distance_pct = abs(current - sl_price) / current * 100

        return {
            "sl_price": sl_price,
            "sl_type": "structure_hl" if is_hl else "swing_low",
            "distance_pct": distance_pct,
            "invalidation_level": last_low_price,
            "is_hl": is_hl,
            "pivot_idx": last_low_idx,
        }

    else:  # SHORT
        # Trouver le dernier swing high (LH dans une tendance baissiere)
        highs = [(idx, price) for idx, price, typ in pivots if typ == "high"]
        if not highs:
            return None

        last_high_idx, last_high_price = highs[-1]

        is_lh = True
        if len(highs) >= 2:
            prev_high_price = highs[-2][1]
            is_lh = last_high_price < prev_high_price

        buffer = last_high_price * buffer_pct
        sl_price = last_high_price + buffer

        distance_pct = abs(current - sl_price) / current * 100

        return {
            "sl_price": sl_price,
            "sl_type": "structure_lh" if is_lh else "swing_high",
            "distance_pct": distance_pct,
            "invalidation_level": last_high_price,
            "is_lh": is_lh,
            "pivot_idx": last_high_idx,
        }
