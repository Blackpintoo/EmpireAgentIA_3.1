"""
Lightweight on-chain listener stub.

In production this module would connect to websocket endpoints (etherscan,
chain-specific RPCs, etc.). For now we provide a minimal scaffold so that
the agent can rely on a common API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional
import time
import logging

logger = logging.getLogger("whale.onchain")


@dataclass
class OnchainEvent:
    ts: float
    wallet: str
    symbol: str
    side: str
    amount: float
    tx_hash: str
    meta: Dict[str, Any]


class OnchainListener:
    def __init__(self, providers: Iterable[str], poll_seconds: float = 15.0):
        self.providers = list(providers)
        self.poll_seconds = poll_seconds
        self._running = False
        self._callback: Optional[Callable[[OnchainEvent], None]] = None

    def start(self, callback: Callable[[OnchainEvent], None]) -> None:
        """
        Register a callback invoked for each on-chain event.
        Real implementation would spin up async tasks; here we only set state.
        """
        self._callback = callback
        self._running = True
        logger.info("[OnchainListener] started with providers=%s", self.providers)

    def stop(self) -> None:
        self._running = False
        logger.info("[OnchainListener] stopped")

    def tick(self) -> None:
        """
        Placeholder polling function. In tests we can call this and feed mocked
        events through `emit`.
        """
        if not self._running:
            return
        time.sleep(0)  # no-op yielding to event loop / cooperative schedulers

    def emit(self, event: OnchainEvent) -> None:
        if not self._running or not self._callback:
            logger.debug("[OnchainListener] drop event %s (not running)", event)
            return
        self._callback(event)
