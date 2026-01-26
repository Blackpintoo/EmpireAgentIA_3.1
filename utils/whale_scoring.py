"""
Utility functions to score whale wallets and copy-trading opportunities.

The module keeps the math intentionally transparent so that scores can be
reasoned about and overridden from configuration files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def compute_trust_score(
    winrate_30d: float,
    pnl_ratio_30d: float,
    followers: int,
    age_days: int,
    verified_social: bool = False,
    blacklist_hits: int = 0,
) -> float:
    """
    Aggregate a 0-1 trust score for a whale wallet / account.

    - winrate_30d: 0..1
    - pnl_ratio_30d: profit factor or Sharpe-like ratio (0..infinity)
    - followers: social proof (0..infinity)
    - age_days: how long the wallet has been tracked
    - verified_social: manual / social verification (twitter / mirror etc)
    - blacklist_hits: number of red flags (rugpull, sandwich, suspicious activity)
    """

    winrate_component = _clip(winrate_30d)

    # Profit ratio -> convert to 0..1 using soft saturation
    pnl_component = _clip(pnl_ratio_30d / (pnl_ratio_30d + 4.0))

    # Followers saturating after 50k
    follower_component = _clip((followers or 0) / 50_000.0)

    # Age saturating after 180 days
    age_component = _clip((age_days or 0) / 180.0)

    verification_bonus = 0.1 if verified_social else 0.0
    blacklist_penalty = min(0.5, 0.1 * max(0, blacklist_hits))

    raw = (
        0.35 * winrate_component
        + 0.35 * pnl_component
        + 0.15 * follower_component
        + 0.15 * age_component
        + verification_bonus
        - blacklist_penalty
    )
    return _clip(raw)


def compute_signal_score(
    entry_confidence: float,
    volume_usd: float,
    price_impact_bps: float,
    age_sec: float,
    slippage_bps: float,
    setup_quality: float,
    volatility_zscore: float,
) -> float:
    """
    Score a single signal in 0..1.

    - entry_confidence: ML / heuristic confidence 0..1
    - volume_usd: executed size (prefer big whales, saturate above 1M)
    - price_impact_bps: smaller is better
    - age_sec: staleness (older -> lower score)
    - slippage_bps: smaller is better
    - setup_quality: discretionary quality 0..1
    - volatility_zscore: penalise if volatility spike
    """

    conf_component = _clip(entry_confidence)
    volume_component = _clip(volume_usd / (volume_usd + 1_000_000.0))

    impact_penalty = _clip(1.0 - (price_impact_bps / 50.0))
    slippage_penalty = _clip(1.0 - (slippage_bps / 40.0))

    age_penalty = _clip(max(0.0, 1.0 - (age_sec / 900.0)))  # degrade after 15 minutes

    quality_component = _clip(setup_quality)
    volatility_penalty = _clip(1.0 - max(0.0, volatility_zscore) / 5.0)

    raw = (
        0.30 * conf_component
        + 0.20 * volume_component
        + 0.15 * quality_component
        + 0.10 * impact_penalty
        + 0.10 * slippage_penalty
        + 0.10 * age_penalty
        + 0.05 * volatility_penalty
    )

    return _clip(raw)


def ewma(prev: Optional[float], value: float, alpha: float = 0.2) -> float:
    """
    Simple exponentially-weighted moving average with clipping in [0, 1].
    """
    if prev is None:
        return _clip(value)
    prev = _clip(prev)
    return _clip(alpha * value + (1.0 - alpha) * prev)


@dataclass
class ScoreBundle:
    trust_score: float
    signal_score: float

    def asdict(self) -> dict:
        return {"trust_score": self.trust_score, "signal_score": self.signal_score}

    @property
    def composite(self) -> float:
        return _clip(self.trust_score * 0.6 + self.signal_score * 0.4)
