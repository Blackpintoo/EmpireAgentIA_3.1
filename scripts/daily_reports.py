"""Daily reporting helper for EmpireAgentIA.

Examples:
    python -m scripts.daily_reports --days 1 --notify-telegram
    python -m scripts.daily_reports --start 2025-09-01 --end 2025-09-02 --notify-email
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from scripts.performance_report import (
    generate_report,
    print_table,
    format_float,
)
from scripts.performance_alert import send_email
from utils.telegram_client import send_message as send_telegram


DATE_FMT = "%Y-%m-%d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rapport quotidien EmpireAgentIA")
    parser.add_argument("--start", type=str, help="Début YYYY-MM-DD (inclus)")
    parser.add_argument("--end", type=str, help="Fin YYYY-MM-DD (exclu)")
    parser.add_argument("--days", type=int, help="Alternative start/end : fenêtre sur N jours", default=1)
    parser.add_argument("--symbols", nargs="*", help="Limiter à certains symboles")

    parser.add_argument("--notify-telegram", action="store_true", help="Envoyer le rapport via Telegram")
    parser.add_argument("--telegram-kind", type=str, default="status")

    parser.add_argument("--notify-email", action="store_true", help="Envoyer le rapport par email (voir variables SMTP_*)")
    parser.add_argument("--email-to", type=str, help="Destinataire override")
    parser.add_argument("--email-subject", type=str, default="EmpireAgentIA Daily Report")

    return parser.parse_args()


def compute_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start and args.end:
        start = datetime.strptime(args.start, DATE_FMT).replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end, DATE_FMT).replace(tzinfo=timezone.utc)
    else:
        days = max(1, int(args.days or 1))
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
    if end <= start:
        raise ValueError("La date de fin doit être postérieure à la date de début")
    return start, end


def build_message(rows: List[List[str]], equity_start: float | None, equity_end: float | None) -> str:
    lines = ["EmpireAgentIA Daily Report", "==========================", ""]
    for row in rows:
        lines.append(" | ".join(row))
    if equity_start is not None and equity_end is not None:
        delta = equity_end - equity_start
        pct = (delta / equity_start * 100.0) if equity_start else 0.0
        lines.append("")
        lines.append(f"Equity start: {equity_start:.2f} | Equity end: {equity_end:.2f} | Delta={delta:.2f} ({pct:.2f}%)")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    start, end = compute_range(args)

    rows, equity_start, equity_end, trade_stats, pnl_stats, symbols = generate_report(start, end, args.symbols)

    if not symbols:
        print("Aucune donnée pour la période demandée.")
        return

    print_table(rows)
    if equity_start is not None and equity_end is not None:
        delta = equity_end - equity_start
        pct = (delta / equity_start * 100.0) if equity_start else 0.0
        print()
        print(f"Equity start: {equity_start:.2f} | Equity end: {equity_end:.2f} | Delta={delta:.2f} ({pct:.2f}%)")

    message = build_message(rows, equity_start, equity_end)

    if args.notify_telegram:
        ok = send_telegram(message, kind=args.telegram_kind, force=True)
        print("Telegram envoyé" if ok else "Échec envoi Telegram")

    if args.notify_email:
        send_email(message, args.email_subject, args.email_to)


if __name__ == "__main__":
    main()
