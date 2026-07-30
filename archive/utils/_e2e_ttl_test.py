import argparse
import asyncio
import os
import sys

# --- Assure que la racine du projet est dans sys.path (parent de utils/) ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from orchestrator.orchestrator import Orchestrator, _start_tg_callback_worker_once


def _pick_price(orch: Orchestrator, symbol: str, side: str):
    """Récupère un prix utilisable (tick ou mid bid/ask)."""
    price = None
    # 1) helper du client
    try:
        if hasattr(orch.mt5, "get_last_price"):
            price = orch.mt5.get_last_price(symbol, side=("BUY" if side == "LONG" else "SELL"))
    except Exception:
        price = None
    # 2) tick direct
    if price is None:
        try:
            tick = orch.mt5.get_tick(symbol)
            if tick:
                if isinstance(tick, dict):
                    price = tick.get("last") or ((tick.get("bid") or 0) + (tick.get("ask") or 0)) / 2
                else:
                    last = getattr(tick, "last", 0.0)
                    bid = getattr(tick, "bid", 0.0)
                    ask = getattr(tick, "ask", 0.0)
                    price = last or ((bid + ask) / 2 if (bid and ask) else None)
        except Exception:
            price = None
    return float(price) if price else None


async def main(args):
    # Initialise un orchestrateur pour un symbole
    orch = Orchestrator(args.symbol)

    # Dry-run : monkey patch pour ne PAS envoyer d’ordre réel
    if args.dry_run:
        def fake_place_order(symbol, action, volume, price=None, sl=None, tp=None):
            print(f"[DRY-RUN] place_order({symbol}, {action}, vol={volume}, sl={sl}, tp={tp})")
            return {"retcode": 10009, "order": 999999}
        orch.mt5.place_order = fake_place_order

    # Démarre l’écoute des boutons Telegram (✅ / ❌)
    _start_tg_callback_worker_once()

    # TTL de la proposition
    orch.proposal_ttl_secs = int(args.ttl)

    # Récupère un prix
    price = _pick_price(orch, args.symbol, args.dir)
    if price is None:
        raise SystemExit("Impossible de récupérer un prix (ouvre MT5 et vérifie que le symbole est coté).")

    # SL/TP
    sl, tp = args.sl, args.tp
    if sl is None or tp is None:
        # marge en % autour du prix si SL/TP non fournis
        delta = max(1.0, price * (args.pct / 100.0))  # ex: pct=0.2 -> ±0.2%
        if args.dir == "LONG":
            sl = price - delta
            tp = price + 1.5 * delta
        else:
            sl = price + delta
            tp = price - 1.5 * delta

    # Message de test (boutons inclus par _send_validation_proposal)
    msg = (
        f"🔬 TEST E2E (TTL={args.ttl}s) — {args.symbol} {args.dir}\n"
        f"Prix: {price:.2f}\nSL: {sl:.2f} | TP: {tp:.2f}\n"
        f"Lots: {args.lots:.3f}\n"
        f"{'(DRY-RUN)' if args.dry_run else ''}"
    )

    await orch._send_validation_proposal(msg, args.dir, price, sl, tp, args.lots)
    print("→ Proposition envoyée avec boutons sur Telegram. Cliquez ✅ pour exécuter ou ❌ pour rejeter.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSD")
    p.add_argument("--dir", choices=["LONG", "SHORT"], default="LONG")
    p.add_argument("--lots", type=float, default=0.01)
    p.add_argument("--sl", type=float, default=None)
    p.add_argument("--tp", type=float, default=None)
    p.add_argument("--ttl", type=int, default=90, help="Durée de validité en secondes")
    p.add_argument("--pct", type=float, default=0.2, help="Marge % pour SL/TP si non fournis")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(main(args))
