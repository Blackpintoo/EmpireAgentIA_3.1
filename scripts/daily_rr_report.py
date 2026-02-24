#!/usr/bin/env python3
# scripts/daily_rr_report.py
# FIX 2026-02-24: Rapport quotidien RR réalisé par symbole (Directive 10)
"""
Analyse deals_history.csv sur les N derniers jours :
- Reconstitue les trades (entry=0 ouverture, entry=1 fermeture)
- Calcule WR, gain moyen, perte moyenne, RR réalisé par symbole
- Alerte si RR < 0.5 et >= 5 trades
- Envoie résumé Telegram si disponible
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CSV_PATH = os.path.join(ROOT, "data", "deals_history.csv")
LOOKBACK_DAYS = 7
ACTIVE_SYMBOLS = {"BTCUSD", "BNBUSD", "SOLUSD", "XAUUSD", "NAS100", "SP500", "EURUSD", "USDJPY", "GBPUSD"}


def load_deals(days: int = LOOKBACK_DAYS) -> list[dict]:
    """Charge les deals des N derniers jours."""
    if not os.path.exists(CSV_PATH):
        print(f"[ERREUR] {CSV_PATH} introuvable")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    deals = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("time,"):
                continue
            parts = line.split(",")
            if len(parts) < 13:
                continue
            try:
                t = int(parts[0])
                if t < cutoff:
                    continue
                deals.append({
                    "time": t,
                    "symbol": parts[1],
                    "type": int(parts[2]),
                    "entry": int(parts[3]),
                    "volume": float(parts[4]),
                    "price": float(parts[5]),
                    "profit": float(parts[6]),
                    "position_id": parts[11],
                })
            except (ValueError, IndexError):
                continue
    return deals


def reconstruct_trades(deals: list[dict]) -> list[dict]:
    """Reconstitue les trades à partir des deals (entry=0 ouverture, entry=1 fermeture)."""
    by_pos = defaultdict(list)
    for d in deals:
        by_pos[d["position_id"]].append(d)

    trades = []
    for pos_id, pos_deals in by_pos.items():
        opens = [d for d in pos_deals if d["entry"] == 0]
        closes = [d for d in pos_deals if d["entry"] == 1]
        if not opens or not closes:
            continue

        symbol = opens[0]["symbol"]
        pnl = sum(d["profit"] for d in pos_deals)
        trades.append({
            "symbol": symbol,
            "position_id": pos_id,
            "pnl": pnl,
            "is_win": pnl > 0,
        })
    return trades


def compute_stats(trades: list[dict]) -> dict[str, dict]:
    """Calcule stats par symbole."""
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)

    stats = {}
    for sym in sorted(by_sym.keys()):
        sym_trades = by_sym[sym]
        n = len(sym_trades)
        wins = [t for t in sym_trades if t["is_win"]]
        losses = [t for t in sym_trades if not t["is_win"]]
        wr = len(wins) / n * 100 if n > 0 else 0.0
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0
        rr = avg_win / avg_loss if avg_loss > 0 else float("inf") if avg_win > 0 else 0.0
        total_pnl = sum(t["pnl"] for t in sym_trades)

        alert = ""
        if rr < 0.5 and n >= 5:
            alert = "ALERTE"
        elif rr < 1.0 and n >= 5:
            alert = "ATTENTION"

        stats[sym] = {
            "trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "wr": wr,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "rr": rr,
            "total_pnl": total_pnl,
            "alert": alert,
        }
    return stats


def format_report(stats: dict[str, dict], days: int) -> str:
    """Formate le rapport en texte."""
    lines = [
        f"{'='*60}",
        f"  RAPPORT RR QUOTIDIEN — {days} derniers jours",
        f"  Généré le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"{'='*60}",
        "",
        f"  {'Symbole':<10} {'Trades':>6} {'WR%':>6} {'Gain moy':>10} {'Perte moy':>10} {'RR':>6} {'P&L':>10} {'Statut':>10}",
        f"  {'-'*10} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*6} {'-'*10} {'-'*10}",
    ]
    for sym, s in stats.items():
        rr_str = f"{s['rr']:.2f}" if s['rr'] != float("inf") else "INF"
        lines.append(
            f"  {sym:<10} {s['trades']:>6} {s['wr']:>5.1f}% {s['avg_win']:>+10.2f} {-s['avg_loss']:>10.2f} {rr_str:>6} {s['total_pnl']:>+10.2f} {s['alert']:>10}"
        )
    lines.append(f"\n{'='*60}")
    return "\n".join(lines)


def format_telegram(stats: dict[str, dict], days: int) -> str:
    """Formate le message Telegram."""
    lines = [f"📊 Rapport RR — {days}j\n"]
    for sym, s in stats.items():
        if s["rr"] == float("inf"):
            emoji = "🟢"
            rr_str = "∞"
        elif s["rr"] >= 1.0:
            emoji = "🟢"
            rr_str = f"{s['rr']:.2f}"
        elif s["rr"] >= 0.5:
            emoji = "🟡"
            rr_str = f"{s['rr']:.2f}"
        else:
            emoji = "🔴"
            rr_str = f"{s['rr']:.2f}"
        lines.append(f"{emoji} {sym}: {s['trades']}T WR={s['wr']:.0f}% RR={rr_str} P&L={s['total_pnl']:+.0f}$")
    return "\n".join(lines)


def main():
    deals = load_deals(LOOKBACK_DAYS)
    if not deals:
        print("[INFO] Aucun deal trouvé sur la période")
        return 0

    trades = reconstruct_trades(deals)
    if not trades:
        print("[INFO] Aucun trade complet reconstitué")
        return 0

    stats = compute_stats(trades)
    report = format_report(stats, LOOKBACK_DAYS)
    print(report)

    # Envoi Telegram si disponible
    try:
        from utils.telegram_client import send_telegram_message
        tg_msg = format_telegram(stats, LOOKBACK_DAYS)
        send_telegram_message(text=tg_msg, kind="daily_rr_report", force=True)
        print("\n[OK] Rapport envoyé sur Telegram")
    except ImportError:
        print("\n[INFO] Module Telegram non disponible — rapport console uniquement")
    except Exception as e:
        print(f"\n[WARN] Envoi Telegram échoué: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
