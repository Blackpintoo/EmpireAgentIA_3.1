#!/usr/bin/env python
"""
Helper to trim open inventory on MT5.
Default behaviour targets EURUSD and reduces the oldest trades on the heavy side.
Run with --dry-run (default) to inspect the plan, add --execute to send close orders.
"""

import argparse
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from utils.config import get_symbol_profile
from utils.mt5_client import MT5Client, mt5


class PositionRecord:
    """Light wrapper around an MT5 position."""

    def __init__(self, raw) -> None:
        self.raw = raw
        self.ticket: int = int(getattr(raw, "ticket", 0) or 0)
        pos_type = int(getattr(raw, "type", 0) or 0)
        buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0) if mt5 else 0
        self.side: str = "BUY" if pos_type == buy_type else "SELL"
        self.volume: float = float(getattr(raw, "volume", 0.0) or 0.0)
        self.profit: float = float(getattr(raw, "profit", 0.0) or 0.0)
        self.swap: float = float(getattr(raw, "swap", 0.0) or 0.0)
        opened = float(getattr(raw, "time", 0) or 0)
        if opened > 0:
            self.open_time = datetime.fromtimestamp(opened, tz=timezone.utc)
        else:
            self.open_time = datetime.now(timezone.utc)

    @property
    def age_hours(self) -> float:
        return max(
            0.0,
            (datetime.now(timezone.utc) - self.open_time).total_seconds() / 3600.0,
        )

    @property
    def net_pl(self) -> float:
        return self.profit + self.swap


def load_positions(client: MT5Client, symbol: str) -> Tuple[str, List[PositionRecord]]:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 module is not available")
    real_symbol = client.resolve_symbol(symbol)
    client.ensure_symbol(symbol)
    raw_positions = mt5.positions_get(symbol=real_symbol) or []  # type: ignore[attr-defined]
    positions = [PositionRecord(p) for p in raw_positions if float(getattr(p, "volume", 0.0) or 0.0) > 0]
    return real_symbol, positions


def pick_by_volume(
    candidates: List[PositionRecord],
    target_volume: float,
    lot_step: float,
    already_marked: Dict[int, str],
    reason: str,
) -> List[Tuple[PositionRecord, str]]:
    picked: List[Tuple[PositionRecord, str]] = []
    remaining = max(0.0, target_volume)
    for pos in sorted(candidates, key=lambda p: (p.open_time, p.ticket)):
        if remaining <= 1e-9:
            break
        if pos.ticket in already_marked:
            continue
        picked.append((pos, reason))
        already_marked[pos.ticket] = reason
        remaining -= pos.volume
    return picked


def pick_by_count(
    candidates: List[PositionRecord],
    target_count: int,
    already_marked: Dict[int, str],
    reason: str,
) -> List[Tuple[PositionRecord, str]]:
    picked: List[Tuple[PositionRecord, str]] = []
    remaining = max(0, target_count)
    for pos in sorted(candidates, key=lambda p: (p.net_pl, -p.age_hours, p.ticket)):
        if remaining <= 0:
            break
        if pos.ticket in already_marked:
            continue
        picked.append((pos, reason))
        already_marked[pos.ticket] = reason
        remaining -= 1
    return picked


def build_close_plan(
    positions: List[PositionRecord],
    lot_step: float,
    keep_net_volume: float,
    max_positions: Optional[int],
    max_close: Optional[int],
) -> List[Tuple[PositionRecord, str]]:
    buys = [p for p in positions if p.side == "BUY"]
    sells = [p for p in positions if p.side == "SELL"]
    vol_buy = sum(p.volume for p in buys)
    vol_sell = sum(p.volume for p in sells)
    net_volume = vol_buy - vol_sell

    plan: List[Tuple[PositionRecord, str]] = []
    marked: Dict[int, str] = {}

    excess = abs(net_volume) - keep_net_volume
    if excess > 1e-6 and lot_step > 0:
        side = "BUY" if net_volume > 0 else "SELL"
        to_trim = math.ceil(excess / lot_step) * lot_step
        source = buys if side == "BUY" else sells
        plan.extend(pick_by_volume(source, to_trim, lot_step, marked, "net_balance"))

    if max_positions and max_positions > 0:
        remaining_after_mark = len(positions) - len(marked)
        if remaining_after_mark > max_positions:
            need = remaining_after_mark - max_positions
            residual = [p for p in positions if p.ticket not in marked]
            plan.extend(pick_by_count(residual, need, marked, "excess_inventory"))

    if max_close and max_close > 0 and len(plan) > max_close:
        plan = plan[:max_close]

    return plan


def close_position(client: MT5Client, real_symbol: str, pos: PositionRecord, comment: str, deviation: Optional[int]) -> Dict[str, object]:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 module is not available")
    buy_type = getattr(mt5, "ORDER_TYPE_BUY", 0)
    sell_type = getattr(mt5, "ORDER_TYPE_SELL", 1)
    action_deal = getattr(mt5, "TRADE_ACTION_DEAL", 1)

    order_type = sell_type if pos.side == "BUY" else buy_type
    tick = None
    try:
        tick = mt5.symbol_info_tick(real_symbol)  # type: ignore[attr-defined]
    except Exception:
        tick = None
    price = None
    if tick:
        price = float(getattr(tick, "ask", None) if order_type == buy_type else getattr(tick, "bid", None))

    request: Dict[str, object] = {
        "action": action_deal,
        "symbol": real_symbol,
        "type": order_type,
        "position": pos.ticket,
        "volume": pos.volume,
        "deviation": deviation,
        "magic": 0,
        "comment": comment[:30],
    }
    if price is not None:
        request["price"] = price

    try:
        result = mt5.order_send(request)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "ticket": pos.ticket, "request": request}

    return client._osr_to_dict(result)  # type: ignore[attr-defined]


def current_profile_step(symbol: str) -> float:
    profile = get_symbol_profile(symbol) or {}
    inst = profile.get("instrument") or {}
    try:
        return float(inst.get("lot_step") or 0.01)
    except Exception:
        return 0.01


def main() -> None:
    parser = argparse.ArgumentParser(description="Trim open MT5 inventory for a symbol.")
    parser.add_argument("--symbol", default="EURUSD", help="Canonical symbol to rebalance (default: EURUSD).")
    parser.add_argument("--keep-net-volume", type=float, default=0.05, help="Target absolute net volume to keep (lots).")
    parser.add_argument("--max-positions", type=int, default=200, help="Maximum open positions to keep after trimming.")
    parser.add_argument("--max-close", type=int, default=80, help="Cap number of closes in a single run.")
    parser.add_argument("--comment", default="inventory_trim", help="Comment to set on close orders.")
    parser.add_argument("--deviation", type=int, default=None, help="Override slippage in points.")
    parser.add_argument("--execute", action="store_true", help="Send close orders instead of dry-run.")
    args = parser.parse_args()

    if mt5 is None:
        raise SystemExit("MetaTrader5 module is not available in this environment.")

    client = MT5Client()
    real_symbol, positions = load_positions(client, args.symbol)
    if not positions:
        print(f"No open positions for {args.symbol}.")
        return

    lot_step = current_profile_step(args.symbol)
    plan = build_close_plan(positions, lot_step, args.keep_net_volume, args.max_positions, args.max_close)

    print(f"Open positions for {args.symbol}: {len(positions)} (buy {sum(p.volume for p in positions if p.side == 'BUY'):.2f} lots, sell {sum(p.volume for p in positions if p.side == 'SELL'):.2f} lots)")
    print(f"Selected {len(plan)} positions to close (lot step {lot_step}).")
    for pos, reason in plan:
        print(
            f" - ticket {pos.ticket} | {pos.side} {pos.volume:.2f} | PnL {pos.net_pl:.2f} | age {pos.age_hours:.1f}h | reason={reason}"
        )

    if not plan:
        return

    if not args.execute:
        print("Dry-run only. Use --execute to send close orders.")
        return

    deviation = args.deviation
    results = []
    for pos, reason in plan:
        res = close_position(client, real_symbol, pos, f"{args.comment}:{reason}", deviation)
        res["ticket"] = pos.ticket
        res["side"] = pos.side
        res["volume"] = pos.volume
        res["reason"] = reason
        results.append(res)

    ok = [r for r in results if r.get("ok")]
    ko = [r for r in results if not r.get("ok")]
    print(f"Close orders done. Success={len(ok)} Errors={len(ko)}")
    for r in ko:
        print(f" * ticket {r.get('ticket')} failed: {r.get('retcode')} {r.get('comment')} {r.get('error')}")


if __name__ == "__main__":
    main()

