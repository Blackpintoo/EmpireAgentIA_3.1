"""
Prometheus metrics helpers (optional).
"""
from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Gauge
except Exception:  # pragma: no cover
    Gauge = None  # type: ignore


class _DummyGauge:
    def labels(self, *args: Any, **kwargs: Any) -> "_DummyGauge":
        return self

    def set(self, value: float) -> None:  # pragma: no cover
        return None


_metrics_enabled = Gauge is not None

if _metrics_enabled:
    WHALE_TRUST_SCORE = Gauge(
        "whale_trust_score",
        "Dernier trust score calculé pour un whale signal",
        ["symbol", "wallet"],
    )
    WHALE_SIGNAL_SCORE = Gauge(
        "whale_signal_score",
        "Dernier signal score calculé pour un whale signal",
        ["symbol", "wallet"],
    )
    WHALE_LATENCY_MS = Gauge(
        "whale_latency_ms",
        "Latence (ms) entre la détection et l'ingestion",
        ["symbol", "source"],
    )
    WHALE_TRUST_EWMA = Gauge(
        "whale_trust_ewma",
        "EWMA du trust score par symbole",
        ["symbol"],
    )
    WHALE_PF_30D = Gauge(
        "whale_profit_factor_30d",
        "Profit factor 30j estimé (statistiques whale)",
        ["wallet"],
    )
else:
    WHALE_TRUST_SCORE = _DummyGauge()
    WHALE_SIGNAL_SCORE = _DummyGauge()
    WHALE_LATENCY_MS = _DummyGauge()
    WHALE_TRUST_EWMA = _DummyGauge()
    WHALE_PF_30D = _DummyGauge()


def record_whale_decision(symbol: str, wallet: str, trust: float, signal: float, latency_ms: float, source: str) -> None:
    WHALE_TRUST_SCORE.labels(symbol=symbol, wallet=wallet).set(float(trust))
    WHALE_SIGNAL_SCORE.labels(symbol=symbol, wallet=wallet).set(float(signal))
    WHALE_LATENCY_MS.labels(symbol=symbol, source=source or "unknown").set(float(latency_ms))


def record_whale_pf(wallet: str, profit_factor_30d: float) -> None:
    WHALE_PF_30D.labels(wallet=wallet).set(float(profit_factor_30d))


def record_whale_trust_ewma(symbol: str, value: float) -> None:
    WHALE_TRUST_EWMA.labels(symbol=symbol).set(float(value))
