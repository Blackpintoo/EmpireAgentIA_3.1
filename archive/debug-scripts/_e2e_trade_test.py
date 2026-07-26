# _e2e_trade_test.py
import argparse
import asyncio
import math
from datetime import datetime, timezone

import MetaTrader5 as mt5

from orchestrator.orchestrator import Orchestrator, _start_tg_callback_worker_once
from utils.logger import logger
from utils.config import get_symbol_profile
from utils.mt5_client import MT5Client


def _quantize(value: float, step: float, minimum: float) -> float:
    if step and step > 0:
        q = round(value / step) * step
    else:
        q = value
    return max(minimum or 0.0, q)


async def main():
    parser = argparse.ArgumentParser(description="E2E test: proposition avec boutons Telegram ✅/❌")
    parser.add_argument("--symbol", default="BTCUSD", help="Symbole (ex: BTCUSD, XAUUSD, EURUSD, LINKUSD)")
    parser.add_argument("--side", default="LONG", choices=["LONG", "SHORT"], help="Direction du trade test")
    parser.add_argument("--wait", type=int, default=600, help="Temps d'attente (sec) pour cliquer sur le bouton")
    parser.add_argument("--lots", type=float, default=0.0, help="Lots explicites (sinon calculés)")
    parser.add_argument("--no-stops", action="store_true", help="N'envoie pas de SL/TP (test MT5)")
    args = parser.parse_args()

    sym = args.symbol.upper()
    side = args.side.upper()

    # MT5 prêt
    MT5Client.initialize_if_needed()
    o = Orchestrator(sym)  # enregistre aussi l'instance dans le registry
    if hasattr(o, 'require_sl_tp') and getattr(args, 'no_stops', False):
        o.require_sl_tp = False
    o.auto_execute = False
    o.use_telegram_validation = True
    o.mt5.ensure_symbol(sym)

    # Prix courant
    price = o._get_last_price(sym)
    if price is None:
        raise SystemExit(f"[E2E] Pas de prix pour {sym}, abandon.")

    # ATR pour SL/TP
    # ATR pour SL/TP
    atr = o._compute_atr(sym, timeframe="M30") or o._compute_atr(sym, timeframe="H1")
    prof = get_symbol_profile(sym) or {}
    ori = prof.get("orchestrator", {}) or {}
    inst = prof.get("instrument", {}) or {}
    point = float(inst.get("point", 0.01))
    mul_sl = float(ori.get("atr_sl_mult", 1.5))
    mul_tp = float(ori.get("atr_tp_mult", 2.5))

    if atr is None or atr <= 0:
        # fallback statique si ATR indisponible
        atr = price * 0.003  # ~0.3%
        logger.info(f"[E2E] ATR indisponible, fallback={atr:.4f}")

    sinfo = mt5.symbol_info(sym)
    mt5_point = getattr(sinfo, "point", None) if sinfo else None
    if mt5_point:
        point = float(mt5_point)
    trade_stops = float(getattr(sinfo, "trade_stops_level", 0) or 0.0) if sinfo else 0.0
    min_stop_distance = trade_stops * point
    price_margin = price * 0.05  # 5% du prix pour garantir marge suffisante
    min_stop_distance = max(min_stop_distance, price_margin)
    if min_stop_distance <= 0:
        min_stop_distance = price * 0.05 or point * 100  # buffer pour tests

    atr_sl = max(mul_sl * atr, min_stop_distance)
    atr_tp = max(mul_tp * atr, min_stop_distance)

    if getattr(args, 'no_stops', False):
        sl = None
        tp = None
    else:
        if side == "LONG":
            sl = price - atr_sl
            tp = price + atr_tp
        else:
            sl = price + atr_sl
            tp = price - atr_tp

    # Lots : soit fournis, soit calculés proprement + quantifiés
    lots = float(args.lots or 0.0)
    if lots <= 0:
        # calcule une taille via risk manager
        stop_distance_points = (atr_sl / max(point, 1e-9)) if getattr(args, 'no_stops', False) else abs(price - sl) / max(point, 1e-9)
        equity = None
        try:
            ai = o.mt5.get_account_info()
            if ai and hasattr(ai, "equity"):
                equity = float(ai.equity)
        except Exception:
            pass
        if equity is None:
            equity = float((prof.get("account") or {}).get("equity_start", 100000.0))
        lots = o.risk.compute_position_size(equity=equity, stop_distance_points=stop_distance_points) or 0.01

    # Respect des contraintes broker
    sinfo = mt5.symbol_info(sym)
    vmin = getattr(sinfo, "volume_min", 0.01) or 0.01
    vstep = getattr(sinfo, "volume_step", 0.01) or 0.01
    lots = _quantize(lots, vstep, vmin)

    # Message + boutons
    sl_txt = f"{sl:.2f}" if sl is not None else "None"
    tp_txt = f"{tp:.2f}" if tp is not None else "None"
    msg = (
        f"🧪 **TEST E2E** {sym} -> {side}\n"
        f"Prix: {price:.2f}\n"
        f"SL: {sl_txt} | TP: {tp_txt}\n"
        f"Lots: {lots:.3f}\n"
        f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} (clique ✅ pour EXECUTER ou ❌ pour REJETER)"
    )
    # Démarre l’écoute des callbacks Telegram
    _start_tg_callback_worker_once()

    # Envoie la proposition AVEC boutons (et mémorise le payload exécutables)
    await o._send_validation_proposal(
        msg,
        side,
        price,
        sl,
        tp,
        lots,
        score_agr=2.0,
        confluence=2,
    )

    print("→ Proposition envoyée avec boutons. Ouvre Telegram et clique sur ✅/❌.")

    # Attente pour laisser le temps de cliquer
    await asyncio.sleep(max(10, int(args.wait)))


if __name__ == "__main__":
    asyncio.run(main())

