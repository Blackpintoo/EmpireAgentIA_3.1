"""Dump current open MT5 positions to reports/open_positions_snapshot_<ts>.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"MetaTrader5 indisponible: {exc}")

from utils.mt5_client import MT5Client


def _serialize_position(pos) -> dict:
    def _get(obj, attr, default=None):
        try:
            val = getattr(obj, attr, default)
            return val if val is not None else default
        except Exception:
            return default

    return {
        "ticket": int(_get(pos, "ticket", 0) or 0),
        "symbol": str(_get(pos, "symbol", "")),
        "type": int(_get(pos, "type", -1) or -1),
        "volume": float(_get(pos, "volume", 0.0) or 0.0),
        "price_open": float(_get(pos, "price_open", 0.0) or 0.0),
        "price_current": float(_get(pos, "price_current", 0.0) or 0.0),
        "sl": float(_get(pos, "sl", 0.0) or 0.0),
        "tp": float(_get(pos, "tp", 0.0) or 0.0),
        "profit": float(_get(pos, "profit", 0.0) or 0.0),
        "swap": float(_get(pos, "swap", 0.0) or 0.0),
        "commission": float(_get(pos, "commission", 0.0) or 0.0),
        "time": int(_get(pos, "time", 0) or 0),
    }


def main() -> None:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    # Initialise et login MT5 via le client standard.
    MT5Client.initialize_if_needed()
    client = MT5Client()

    try:
        raw_positions = mt5.positions_get()  # type: ignore[attr-defined]
    except Exception as exc:
        raise SystemExit(f"Impossible de lire les positions MT5: {exc}")

    positions = [_serialize_position(p) for p in (raw_positions or [])]

    now = datetime.now(timezone.utc)
    out_path = reports_dir / f"open_positions_snapshot_{now.strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "positions": positions,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Snapshot enregistré: {out_path} ({len(positions)} position(s))")


if __name__ == "__main__":
    main()
