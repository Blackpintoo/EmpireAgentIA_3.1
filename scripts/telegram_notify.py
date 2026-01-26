"""
Utility script to send a Telegram status message using the existing client.

Usage example:
    python scripts/telegram_notify.py --text "Empire Agent IA started"
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Optional

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from utils.telegram_client import TelegramClient  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"[telegram_notify] Import error: {exc}", file=sys.stderr)
    sys.exit(1)


def notify(text: str, *, kind: Optional[str] = "status", force: bool = False) -> int:
    client = TelegramClient()
    target_kind = kind or "status"
    if not (client.enabled and client.token and client.chat_id):
        print("[telegram_notify] Telegram not configured (token/chat_id missing or disabled).", file=sys.stderr)
        return 3
    if not client._should_send(target_kind, force):
        print("[telegram_notify] Sending skipped by configuration (allow_kinds / validation-only).", file=sys.stderr)
        return 3
    payload = {
        "chat_id": client.chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    result = client._post("sendMessage", payload)
    if getattr(result, "ok", False):
        print("[telegram_notify] Message sent.")
        return 0
    print("[telegram_notify] Message not sent.", file=sys.stderr)
    return 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a Telegram status message.")
    parser.add_argument("--text", required=True, help="Message body to send.")
    parser.add_argument("--kind", default="status", help="Message kind, defaults to 'status'.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore allow_kinds restrictions and force sending.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return notify(args.text, kind=args.kind, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
