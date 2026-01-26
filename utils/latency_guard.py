"""
Helpers to guard against stale whale signals.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class LatencyStatus:
    ok: bool
    latency_ms: float
    reason: Optional[str] = None


class LatencyGuard:
    """
    Simple guard that ensures we react only to fresh signals and keeps track of
    the latest accepted timestamps to avoid duplication.
    """

    def __init__(self, max_latency_ms: float = 15_000.0):
        self.max_latency_ms = max_latency_ms
        self._last_signal_ts: Optional[float] = None

    def check(self, event_ts: float, received_ts: Optional[float] = None) -> LatencyStatus:
        """
        event_ts: seconds since epoch (float) at origin
        received_ts: optional receive timestamp (defaults to `time.time()`)
        """
        if received_ts is None:
            received_ts = time.time()

        latency_ms = max(0.0, (received_ts - event_ts) * 1000.0)

        if latency_ms > self.max_latency_ms:
            return LatencyStatus(False, latency_ms, reason="latency_too_high")

        if self._last_signal_ts and event_ts <= self._last_signal_ts:
            return LatencyStatus(False, latency_ms, reason="duplicate_or_old")

        self._last_signal_ts = event_ts
        return LatencyStatus(True, latency_ms)

    def reset(self) -> None:
        self._last_signal_ts = None


def guard_latency(event_ts: float, max_latency_ms: float, received_ts: Optional[float] = None) -> LatencyStatus:
    guard = LatencyGuard(max_latency_ms=max_latency_ms)
    return guard.check(event_ts, received_ts)
