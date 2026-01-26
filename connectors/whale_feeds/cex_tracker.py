"""
Centralised exchange whale tracker (stub).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional
import logging
import time

logger = logging.getLogger("whale.cex")


@dataclass
class CexWhaleEvent:
    ts: float
    venue: str
    wallet: str
    symbol: str
    side: str
    size_usd: float
    price: float
    meta: Dict[str, Any]


class CexTracker:
    def __init__(self, venues: Iterable[str], ws_url: Optional[str] = None):
        self.venues = list(venues)
        self.ws_url = ws_url
        self._callback: Optional[Callable[[CexWhaleEvent], None]] = None
        self._connected = False

    def connect(self, callback: Callable[[CexWhaleEvent], None]) -> None:
        """
        Register callback for whale prints. Real implementation would connect
        to a websocket feed (ex: Binance block trades).
        """
        self._callback = callback
        self._connected = True
        logger.info("[CexTracker] connected to venues=%s", self.venues)

    def disconnect(self) -> None:
        self._connected = False
        logger.info("[CexTracker] disconnected")

    def emit(self, event: CexWhaleEvent) -> None:
        if not (self._connected and self._callback):
            logger.debug("[CexTracker] drop event %s (not connected)", event)
            return
        self._callback(event)

    def ping(self) -> None:
        """
        Placeholder keep-alive.
        """
        time.sleep(0)
