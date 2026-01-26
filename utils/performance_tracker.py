"""
Dynamic performance tracker used to derive adaptive weights for voting and analytics.

The tracker stores lightweight exponential moving averages per (symbol, agent,
timeframe, regime) bucket. It is safe to call from multiple agents/orchestrator
components and backs its state with ``data/performance/performance_tracker.json``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DEFAULT_PATH = Path("data") / "performance" / "performance_tracker.json"
_SUCCESS_CODES = {10009, 10008}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class PerformancePoint:
    symbol: str
    agent: str
    timeframe: str
    regime: str
    score: float
    outcome: Optional[float] = None
    executed: Optional[bool] = None
    reward_risk: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class PerformanceTracker:
    """
    Tracks agent quality over time and exposes weights usable for weighted votes.

    Weight formula (bounded in [0.25, 3.5]):
      base 1.0 + 1.5 * outcome_ema + 1.2 * (win_rate - 0.5) + 0.6 * (score_ema - 0.5)
    with early-history dampening and optional inactivity decay.
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        decay: float = 0.85,
        min_history: int = 5,
        inactivity_half_life_days: float = 14.0,
    ) -> None:
        self.decay = float(_clamp(decay, 0.0, 0.999))
        self.alpha = 1.0 - self.decay
        self.min_history = int(max(1, min_history))
        self.inactivity_half_life_days = float(max(1.0, inactivity_half_life_days))

        self.storage_path = Path(storage_path) if storage_path else _DEFAULT_PATH
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self._data: Dict[str, Any] = self._load()

    # ------------------------------------------------------------------ storage
    def _load(self) -> Dict[str, Any]:
        try:
            if self.storage_path.exists():
                raw = self.storage_path.read_text(encoding="utf-8")
                if raw.strip():
                    return json.loads(raw)
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self.storage_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ----------------------------------------------------------------- indexing
    def _bucket_key(self, timeframe: Optional[str], regime: Optional[str]) -> str:
        tf = (timeframe or "NA").upper()
        rg = (regime or "default").lower()
        return f"{tf}|{rg}"

    def _ensure_leaf(self, symbol: str, agent: str, bucket: str) -> Dict[str, Any]:
        sym = self._data.setdefault(symbol.upper(), {})
        ag = sym.setdefault(agent.lower(), {})
        leaf = ag.setdefault(
            bucket,
            {
                "count": 0,
                "score_ema": None,
                "outcome_ema": None,
                "win_rate": None,
                "weight": 1.0,
                "last_update": None,
            },
        )
        return leaf

    # ---------------------------------------------------------- weight helpers
    def _normalize_score(self, score: float) -> float:
        """Convert arbitrary score to 0..1 using a logistic squeeze."""
        try:
            score = float(score)
        except Exception:
            return 0.5
        score = _clamp(score, -5.0, 5.0)
        return 1.0 / (1.0 + math.exp(-score))

    def _normalize_outcome(self, outcome: float) -> float:
        """
        Outcome is expected in R-multiples (negative for losses).
        We clamp to [-3, 3] to avoid spikes.
        """
        try:
            outcome = float(outcome)
        except Exception:
            return 0.0
        return _clamp(outcome, -3.0, 3.0)

    def _update_weight(self, leaf: Dict[str, Any]) -> float:
        count = int(leaf.get("count") or 0)
        score_ema = float(leaf.get("score_ema") or 0.5)
        outcome_ema = float(leaf.get("outcome_ema") or 0.0)
        win_rate = leaf.get("win_rate")
        bonus = 0.0
        if win_rate is not None:
            bonus += (float(win_rate) - 0.5) * 1.2
        bonus += outcome_ema * 1.5
        bonus += (score_ema - 0.5) * 0.6
        if count < self.min_history:
            bonus *= count / float(self.min_history)
        weight = 1.0 + bonus
        weight = _clamp(weight, 0.25, 3.5)
        leaf["weight"] = weight
        return weight

    def _apply_inactivity_decay(self, leaf: Dict[str, Any]) -> None:
        last_raw = leaf.get("last_update")
        if not last_raw:
            return
        try:
            last_dt = datetime.fromisoformat(str(last_raw))
        except Exception:
            return
        delta = _now_utc() - last_dt
        if delta <= timedelta(days=self.inactivity_half_life_days):
            return
        decay_steps = delta.days / self.inactivity_half_life_days
        factor = 0.5 ** decay_steps
        leaf["score_ema"] = 0.5 + (leaf.get("score_ema", 0.5) - 0.5) * factor
        leaf["outcome_ema"] = (leaf.get("outcome_ema", 0.0) or 0.0) * factor
        win_rate = leaf.get("win_rate")
        if win_rate is not None:
            leaf["win_rate"] = 0.5 + (float(win_rate) - 0.5) * factor
        leaf["weight"] = 1.0 + (leaf.get("weight", 1.0) - 1.0) * factor
        leaf["weight"] = _clamp(float(leaf["weight"]), 0.25, 3.5)

    # -------------------------------------------------------------- public API
    def record(self, point: PerformancePoint, *, auto_save: bool = True) -> None:
        bucket = self._bucket_key(point.timeframe, point.regime)
        leaf = self._ensure_leaf(point.symbol, point.agent, bucket)

        # Smooth EMAs
        if point.score is not None:
            score_norm = self._normalize_score(point.score)
            prev = leaf.get("score_ema")
            prev_val = float(prev) if prev is not None else score_norm
            leaf["score_ema"] = self.decay * prev_val + self.alpha * score_norm

        if point.outcome is not None:
            out_norm = self._normalize_outcome(point.outcome)
            prev_out = leaf.get("outcome_ema")
            prev_val = float(prev_out) if prev_out is not None else out_norm
            leaf["outcome_ema"] = self.decay * prev_val + self.alpha * out_norm
            win_rate = leaf.get("win_rate")
            win_val = float(win_rate) if win_rate is not None else 0.5
            incr = 1.0 if out_norm > 0 else 0.0
            leaf["win_rate"] = self.decay * win_val + self.alpha * incr
        elif point.executed is not None:
            win_rate = leaf.get("win_rate")
            win_val = float(win_rate) if win_rate is not None else 0.5
            incr = 1.0 if point.executed else 0.0
            leaf["win_rate"] = self.decay * win_val + self.alpha * incr

        leaf["count"] = int(leaf.get("count") or 0) + 1
        leaf["last_update"] = _now_utc().isoformat(timespec="seconds")
        self._update_weight(leaf)

        if auto_save:
            self._save()

    def record_many(self, points: Iterable[PerformancePoint]) -> None:
        for point in points:
            self.record(point, auto_save=False)
        self._save()

    def get_weight(
        self,
        symbol: str,
        agent: str,
        timeframe: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> float:
        bucket = self._bucket_key(timeframe, regime)
        leaf = self._ensure_leaf(symbol, agent, bucket)
        self._apply_inactivity_decay(leaf)
        weight = float(leaf.get("weight") or 1.0)
        return _clamp(weight, 0.25, 3.5)

    def get_bucket_stats(
        self,
        symbol: str,
        agent: str,
        timeframe: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        bucket = self._bucket_key(timeframe, regime)
        leaf = self._ensure_leaf(symbol, agent, bucket)
        self._apply_inactivity_decay(leaf)
        return {
            "weight": float(leaf.get("weight") or 1.0),
            "count": int(leaf.get("count") or 0),
            "score_ema": float(leaf.get("score_ema") or 0.5),
            "outcome_ema": float(leaf.get("outcome_ema") or 0.0),
            "win_rate": leaf.get("win_rate"),
            "last_update": leaf.get("last_update"),
        }

    def compute_weighted_vote(
        self,
        symbol: str,
        signals: Iterable[Dict[str, Any]],
        *,
        regime: Optional[str] = None,
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """
        Return (weighted_score, enriched_signals).
        Each signal dict must expose agent, score, timeframe, and optional outcome.
        """
        total_weight = 0.0
        cumulative = 0.0
        enriched: List[Dict[str, Any]] = []
        for sig in signals:
            agent = str(sig.get("agent") or "unknown")
            timeframe = sig.get("timeframe")
            score = sig.get("score")
            if score is None:
                continue
            stats = self.get_bucket_stats(symbol, agent, timeframe, regime)
            weight = float(stats.get("weight") or 1.0)
            weighted = float(score) * weight
            enriched.append({**sig, "weight": weight, "weighted_score": weighted, "tracker": stats})
            total_weight += abs(weight)
            cumulative += weighted
        avg = cumulative / total_weight if total_weight > 0 else 0.0
        return avg, enriched

    def snapshot(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Provide the strongest buckets sorted by descending weight deviation.
        """
        rows: List[Dict[str, Any]] = []
        for symbol, agents in self._data.items():
            for agent, buckets in agents.items():
                for bucket_key, leaf in buckets.items():
                    weight = float(leaf.get("weight") or 1.0)
                    deviation = weight - 1.0
                    rows.append(
                        {
                            "symbol": symbol,
                            "agent": agent,
                            "bucket": bucket_key,
                            "weight": weight,
                            "count": int(leaf.get("count") or 0),
                            "score_ema": round(float(leaf.get("score_ema") or 0.5), 4),
                            "outcome_ema": round(float(leaf.get("outcome_ema") or 0.0), 4),
                            "win_rate": leaf.get("win_rate"),
                            "last_update": leaf.get("last_update"),
                        }
                    )
        rows.sort(key=lambda r: abs(r["weight"] - 1.0), reverse=True)
        return rows[:top_n]

    def dump(self) -> Dict[str, Any]:
        return self._data


_DEFAULT_TRACKER: Optional[PerformanceTracker] = None


def default_tracker() -> PerformanceTracker:
    global _DEFAULT_TRACKER
    if _DEFAULT_TRACKER is None:
        _DEFAULT_TRACKER = PerformanceTracker()
    return _DEFAULT_TRACKER


def record_trade_event(
    symbol: str,
    agent: str,
    timeframe: str,
    regime: Optional[str],
    score: float,
    retcode: Optional[int],
    outcome_r_multiple: Optional[float] = None,
) -> None:
    """
    Convenience wrapper for orchestrator callbacks.
    """
    executed = retcode in _SUCCESS_CODES if retcode is not None else None
    point = PerformancePoint(
        symbol=symbol,
        agent=agent,
        timeframe=timeframe,
        regime=regime or "default",
        score=score,
        outcome=outcome_r_multiple,
        executed=executed,
    )
    default_tracker().record(point)


__all__ = ["PerformanceTracker", "PerformancePoint", "default_tracker", "record_trade_event"]
