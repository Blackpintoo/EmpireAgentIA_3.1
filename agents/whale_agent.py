"""
Whale copy-trading agent.

Consumes events from connectors (on-chain / CEX / social), computes trust &
signal scores, and exposes a normalised signal to the orchestrator.
"""
from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from utils.logger import logger
from utils.whale_scoring import ScoreBundle, compute_signal_score, compute_trust_score
from utils.latency_guard import LatencyGuard
from utils.metrics import record_whale_decision, record_whale_pf


@dataclass
class WhaleEvent:
    ts: float
    wallet: str
    symbol: str
    side: str  # LONG/SHORT
    price: float
    volume_usd: float
    price_impact_bps: float = 0.0
    slippage_bps: float = 0.0
    volatility_zscore: float = 0.0
    setup_quality: float = 0.5
    entry_confidence: float = 0.5
    stats: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    source: str = "generic"


@dataclass
class WhaleDecision:
    event: WhaleEvent
    scores: ScoreBundle
    latency_ms: float
    reason: Optional[str] = None
    lots: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None


class WhaleAgent:
    def __init__(
        self,
        cfg: Dict[str, Any],
        market_ctx_provider: Callable[[str], Dict[str, Any]],
        stats_provider: Callable[[str], Dict[str, Any]],
        risk_manager,
    ):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.min_trust = float(self.cfg.get("min_trust", 0.6))
        self.min_signal = float(self.cfg.get("min_signal", 0.55))
        self.allow_in_vol_spike = bool(self.cfg.get("allow_in_vol_spike", False))
        self.latency_ms_max = float(self.cfg.get("latency_ms_max", 15_000))
        self.decisions_path = (
            self.cfg.get("storage", {}).get("decisions_csv") or "data/whales_decisions.csv"
        )
        self.market_ctx_provider = market_ctx_provider
        self.stats_provider = stats_provider
        self.risk_manager = risk_manager

        self._latency_guards: Dict[str, LatencyGuard] = {}
        self._pending: Optional[WhaleDecision] = None

        os.makedirs(os.path.dirname(self.decisions_path), exist_ok=True)
        if not os.path.exists(self.decisions_path):
            with open(self.decisions_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "ts",
                        "wallet",
                        "symbol",
                        "side",
                        "trust_score",
                        "signal_score",
                        "lots",
                        "sl",
                        "tp",
                        "latency_ms",
                        "reason",
                        "source",
                    ]
                )

    # ------------------------------------------------------------------ ingest
    def ingest_event(self, event_payload: Dict[str, Any], source: str = "onchain") -> None:
        if not self.enabled:
            return
        event = self._parse_event(event_payload, source)
        if event is None:
            return

        guard = self._latency_guards.setdefault(
            event.wallet,
            LatencyGuard(max_latency_ms=self.latency_ms_max),
        )
        latency_status = guard.check(event.ts)
        if not latency_status.ok:
            logger.debug("[WhaleAgent] ignore event %s latency=%s reason=%s", event.wallet, latency_status.latency_ms, latency_status.reason)
            return

        trust_score = self._compute_trust(event)
        signal_score = self._compute_signal(event)
        scores = ScoreBundle(trust_score=trust_score, signal_score=signal_score)

        reason = None
        if trust_score < self.min_trust:
            reason = "trust_below_threshold"
        elif signal_score < self.min_signal:
            reason = "signal_below_threshold"
        elif (not self.allow_in_vol_spike) and event.volatility_zscore > 3.0:
            reason = "volatility_spike"

        lots = sl = tp = None
        if reason is None:
            risk_result = self._size_position(event, scores)
            if not risk_result or risk_result.get("lots", 0) <= 0:
                reason = risk_result.get("reason", "sizing_failed") if risk_result else "sizing_failed"
            else:
                lots = risk_result["lots"]
                sl = risk_result.get("sl")
                tp = risk_result.get("tp")

        decision = WhaleDecision(
            event=event,
            scores=scores,
            latency_ms=latency_status.latency_ms,
            reason=reason,
            lots=lots,
            sl=sl,
            tp=tp,
        )

        if reason is None:
            self._pending = decision
        else:
            self._pending = None
        self._log_decision(decision)

    # ----------------------------------------------------------------- helpers
    def _parse_event(self, payload: Dict[str, Any], source: str) -> Optional[WhaleEvent]:
        try:
            ts = float(payload.get("ts") or time.time())
            wallet = str(payload["wallet"])
            symbol = str(payload["symbol"]).upper()
            side = str(payload.get("side", "LONG")).upper()
            price = float(payload.get("price"))
            volume_usd = float(payload.get("volume_usd"))
        except Exception as exc:
            logger.warning("[WhaleAgent] invalid event payload=%s err=%s", payload, exc)
            return None

        stats = payload.get("stats") or {}
        meta = payload.get("meta") or {}

        event = WhaleEvent(
            ts=ts,
            wallet=wallet,
            symbol=symbol,
            side=side,
            price=price,
            volume_usd=volume_usd,
            price_impact_bps=float(payload.get("price_impact_bps", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            volatility_zscore=float(payload.get("volatility_zscore", 0.0)),
            setup_quality=float(payload.get("setup_quality", 0.5)),
            entry_confidence=float(payload.get("entry_confidence", 0.5)),
            stats=stats,
            meta={**meta, "source": source},
            source=source,
        )
        return event

    def _compute_trust(self, event: WhaleEvent) -> float:
        stats = self.stats_provider(event.wallet) or {}
        return compute_trust_score(
            winrate_30d=float(stats.get("winrate_30d", event.meta.get("winrate_30d", 0.5))),
            pnl_ratio_30d=float(stats.get("pnl_ratio_30d", event.meta.get("pnl_ratio_30d", 1.0))),
            followers=int(stats.get("followers", event.meta.get("followers", 0))),
            age_days=int(stats.get("age_days", event.meta.get("age_days", 30))),
            verified_social=bool(stats.get("verified", event.meta.get("verified", False))),
            blacklist_hits=int(stats.get("blacklist_hits", event.meta.get("blacklist_hits", 0))),
        )

    def _compute_signal(self, event: WhaleEvent) -> float:
        return compute_signal_score(
            entry_confidence=event.entry_confidence,
            volume_usd=event.volume_usd,
            price_impact_bps=event.price_impact_bps,
            age_sec=max(0.0, time.time() - event.ts),
            slippage_bps=event.slippage_bps,
            setup_quality=event.setup_quality,
            volatility_zscore=event.volatility_zscore,
        )

    def _size_position(self, event: WhaleEvent, scores: ScoreBundle) -> Optional[Dict[str, Any]]:
        market_ctx = self.market_ctx_provider(event.symbol) or {}
        atr = float(market_ctx.get("atr", event.meta.get("atr", 0.0)))
        return self.risk_manager.size_by_scores(
            symbol=event.symbol,
            side=event.side,
            price=event.price,
            atr=atr,
            scores=scores,
        )

    # ----------------------------------------------------------------- main API
    def generate_signal(self) -> Optional[Dict[str, Any]]:
        if not self.enabled or self._pending is None:
            return {"signal": "WAIT"}

        decision = self._pending
        self._pending = None

        payload = {
            "signal": decision.event.side,
            "price": decision.event.price,
            "lots": decision.lots,
            "sl": decision.sl,
            "tp": decision.tp,
            "trust_score": decision.scores.trust_score,
            "signal_score": decision.scores.signal_score,
            "latency_ms": decision.latency_ms,
            "wallet": decision.event.wallet,
            "symbol": decision.event.symbol,
            "source": decision.event.source,
        }
        return payload

    # ------------------------------------------------------------------ logging
    def _log_decision(self, decision: WhaleDecision) -> None:
        try:
            with open(self.decisions_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(decision.event.ts)),
                        decision.event.wallet,
                        decision.event.symbol,
                        decision.event.side,
                        f"{decision.scores.trust_score:.4f}",
                        f"{decision.scores.signal_score:.4f}",
                        decision.lots if decision.lots is not None else "",
                        decision.sl if decision.sl is not None else "",
                        decision.tp if decision.tp is not None else "",
                        f"{decision.latency_ms:.1f}",
                        decision.reason or "",
                        decision.event.source,
                    ]
                )
        except Exception as exc:
            logger.warning("[WhaleAgent] failed to log decision: %s", exc)
        try:
            record_whale_decision(
                decision.event.symbol,
                decision.event.wallet,
                decision.scores.trust_score,
                decision.scores.signal_score,
                decision.latency_ms,
                decision.event.source,
            )
            pf30 = None
            stats = decision.event.stats or {}
            if isinstance(stats, dict):
                pf30 = stats.get("pnl_ratio_30d")
            if pf30 is None:
                pf30 = decision.event.meta.get("pnl_ratio_30d")
            if pf30 is not None:
                record_whale_pf(decision.event.wallet, float(pf30))
        except Exception:
            pass
