# utils/mt5_sim.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time
import itertools
import math

@dataclass
class SimOrderResult:
    retcode: int
    order: Optional[int] = None
    deal: Optional[int] = None

class MT5Sim:
    """
    Simulateur minimaliste pour 'order_send' au marché:
    - Remplit instantanément au prix demandé (ou à défaut bid/ask simulé).
    - Garde un solde virtuel et un registre des positions (sans swaps/commission).
    - Évite toute dépendance au module natif MetaTrader5.
    """
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    # Retcodes de compat
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_REQUOTE = 10031
    TRADE_RETCODE_PRICE_CHANGED = 10032
    TRADE_RETCODE_INVALID_VOLUME = 10030

    def __init__(self, balance: float = 10000.0):
        self._balance = float(balance)
        self._equity = float(balance)
        self._orders = {}
        self._positions = {}
        self._id_gen = itertools.count(100000)
        # Info symbole simplifiée (peut être surchargée par monkeypatch aux tests)
        self._symbol_info = {}
        self._ticks = {}

    # ------------------- API symbol mock -------------------
    def symbol_select(self, symbol: str, _v: bool) -> bool:
        return True

    def symbol_info(self, symbol: str):
        # objet simple avec attributs utilisés
        d = self._symbol_info.get(symbol) or {
            "visible": True,
            "digits": 2,
            "point": 0.01,
            "trade_contract_size": 1.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
            "stops_level": 0,
            "freeze_level": 0,
        }
        return type("Info", (), d)

    def symbol_info_tick(self, symbol: str):
        t = self._ticks.get(symbol)
        if not t:
            # tick par défaut
            t = {"bid": 100.0, "ask": 100.0}
        return type("Tick", (), t)

    def set_symbol_info(self, symbol: str, **kwargs):
        self._symbol_info.setdefault(symbol, {}).update(kwargs)

    def set_tick(self, symbol: str, bid: float, ask: float):
        self._ticks[symbol] = {"bid": float(bid), "ask": float(ask)}

    # ------------------- Trading -------------------
    def order_send(self, request: Dict[str, Any]) -> SimOrderResult:
        if request.get("action") != self.TRADE_ACTION_DEAL:
            return SimOrderResult(retcode=self.TRADE_RETCODE_PRICE_CHANGED)
        symbol = request.get("symbol")
        typ = request.get("type")
        vol = float(request.get("volume") or 0.0)
        if vol <= 0:
            return SimOrderResult(retcode=self.TRADE_RETCODE_INVALID_VOLUME)
        info = self.symbol_info(symbol)
        # aligne volume sur step
        step = float(getattr(info, "volume_step", 0.01) or 0.01)
        vmin = float(getattr(info, "volume_min", 0.01) or 0.01)
        if step > 0:
            units = round((vol - vmin) / step)
            aligned = round(vmin + units * step, 8)
            if not math.isclose(aligned, vol, rel_tol=0, abs_tol=1e-9):
                return SimOrderResult(retcode=self.TRADE_RETCODE_INVALID_VOLUME)
        # prix
        px = request.get("price")
        if px is None:
            tick = self.symbol_info_tick(symbol)
            px = float(tick.ask if typ == self.ORDER_TYPE_BUY else tick.bid)
        px = float(px)
        oid = next(self._id_gen)
        did = next(self._id_gen)
        self._orders[oid] = {"symbol": symbol, "type": typ, "price": px, "volume": vol, "time": time.time()}
        # position virtuelle (pas de netting FIFO ici, c’est un dry-run light)
        self._positions[did] = {"symbol": symbol, "type": typ, "price": px, "volume": vol, "time": time.time()}
        return SimOrderResult(retcode=self.TRADE_RETCODE_DONE, order=oid, deal=did)
