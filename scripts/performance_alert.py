"""Performance alert utility.

Examples:
    python -m scripts.performance_alert --days 7 --target-profit 2500 --symbol BTCUSD ETHUSD
    python -m scripts.performance_alert --start 2025-09-01 --end 2025-10-01 --max-drawdown -1000 --notify-telegram

Alerts can be emitted via Telegram (using existing utils.telegram_client config) and/or email (SMTP env vars).
"""

from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage

from typing import Iterable, List, Optional

from scripts.performance_report import (
    parse_args as pr_parse_args,
    parse_date_range,
    load_trades,
    discover_symbols,
    load_audit_pnl,
    load_equity_series,
    build_table,
    format_float,
)
from utils.telegram_client import send_message as send_telegram


DEFAULT_EMAIL_SUBJECT = "EmpireAgentIA Alert"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EmpireAgentIA performance alerts")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (exclusive)")
    parser.add_argument("--days", type=int, help="Look-back window in days (alternative to start/end)")
    parser.add_argument("--symbols", nargs="*", help="Symbols to include (default all detected)")

    parser.add_argument("--target-profit", type=float, help="Trigger alert when total PnL ≥ target (currency)")
    parser.add_argument("--max-drawdown", type=float, help="Trigger alert when equity change ≤ value (currency)")
    parser.add_argument("--min-success", type=float, help="Trigger alert when success rate ≤ value (percentage)")

    parser.add_argument("--notify-telegram", action="store_true", help="Send alert via Telegram")
    parser.add_argument("--telegram-kind", type=str, default="status", help="Telegram kind (default: status)")

    parser.add_argument("--notify-email", action="store_true", help="Send alert via email (uses SMTP env vars)")
    parser.add_argument("--email-to", type=str, help="Override recipient email address")
    parser.add_argument("--email-subject", type=str, default=DEFAULT_EMAIL_SUBJECT)

    return parser.parse_args()


def success_rate(trade_stats) -> float:
    total_attempts = sum(v.attempts for v in trade_stats.values())
    total_exec = sum(v.executed for v in trade_stats.values())
    if total_attempts == 0:
        return 0.0
    return total_exec / total_attempts * 100.0


def total_pnl(pnl_stats) -> float:
    return sum(v.pnl for v in pnl_stats.values())


def send_email(message: str, subject: str, recipient: Optional[str]) -> None:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "0")) or 587
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    default_to = os.environ.get("SMTP_TO")
    sender = os.environ.get("SMTP_FROM") or user

    to_addr = recipient or default_to

    if not all([host, sender, to_addr]):
        print("Email not sent (SMTP_HOST/SMTP_FROM/SMTP_TO missing).")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(message)

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        print(f"Email alert sent to {to_addr}")
    except Exception as e:
        print(f"Email send failed: {e}")


def build_alert_message(summary_rows: List[List[str]], equity_start: Optional[float], equity_end: Optional[float], triggers: List[str]) -> str:
    lines = []
    lines.append("EmpireAgentIA Performance Alert")
    lines.append("".join(["=" * len(lines[0])]))
    lines.append("Triggers: " + ", ".join(triggers) if triggers else "Triggers: (none)")
    lines.append("")
    for row in summary_rows:
        lines.append(" | ".join(row))
    if equity_start is not None and equity_end is not None:
        delta = equity_end - equity_start
        pct = (delta / equity_start * 100.0) if equity_start else 0.0
        lines.append("")
        lines.append(f"Equity start: {equity_start:.2f} | Equity end: {equity_end:.2f} | Δ={delta:.2f} ({pct:.2f}%)")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    start, end = parse_date_range(args)

    trade_stats = load_trades(start, end, args.symbols)
    symbols = args.symbols or discover_symbols(trade_stats)
    symbols = sorted(set(s.upper() for s in symbols))

    pnl_stats = load_audit_pnl(start, end, symbols or None)
    equity_start, equity_end = load_equity_series(start, end)

    if not symbols:
        print("Aucun symbole détecté dans la période indiquée.")
        return

    rows = build_table(symbols, trade_stats, pnl_stats)
    total = total_pnl(pnl_stats)
    success = success_rate(trade_stats)
    delta = None
    if equity_start is not None and equity_end is not None:
        delta = equity_end - equity_start

    triggers: List[str] = []

    if args.target_profit is not None and total >= args.target_profit:
        triggers.append(f"P&L total {format_float(total)} ≥ cible {args.target_profit}")
    if args.max_drawdown is not None and delta is not None and delta <= args.max_drawdown:
        triggers.append(f"Δ equity {format_float(delta)} ≤ {args.max_drawdown}")
    if args.min_success is not None and success <= args.min_success:
        triggers.append(f"Taux succès {format_float(success)}% ≤ {args.min_success}%")

    if not triggers:
        print("Aucun seuil atteint. Aucun message envoyé.")
        return

    message = build_alert_message(rows, equity_start, equity_end, triggers)

    if args.notify_telegram:
        ok = send_telegram(message, kind=args.telegram_kind, force=True)
        print("Telegram envoyé" if ok else "Échec envoi Telegram")

    if args.notify_email:
        send_email(message, args.email_subject, args.email_to)

    print()
    print(message)


if __name__ == "__main__":
    main()
