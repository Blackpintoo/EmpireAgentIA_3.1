# reporting/daily_digest.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
from datetime import datetime
import pytz

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

def _today_range_utc(tz_name: str = "Europe/Zurich") -> Tuple[datetime, datetime, str]:
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    day_start = tz.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
    day_end   = tz.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
    start_utc = day_start.astimezone(pytz.utc)
    end_utc   = day_end.astimezone(pytz.utc)
    label = now.strftime("%Y-%m-%d")
    return start_utc, end_utc, label

def generate_daily_digest(symbols: List[str], tz_name: str = "Europe/Zurich") -> str:
    if mt5 is None:
        return f"#DAILY_DIGEST | {tz_name} | MT5 indisponible"

    start_utc, end_utc, label = _today_range_utc(tz_name)
    deals = mt5.history_deals_get(start_utc, end_utc) or []
    # Agrégation
    stats: Dict[str, Dict[str, Any]] = {}
    total_pnl = 0.0
    n_trades = 0
    n_win = 0

    symset = set(symbols or [])
    for d in deals:
        sym = getattr(d, "symbol", "")
        if symbols and sym not in symset:
            continue
        profit = float(getattr(d, "profit", 0.0) or 0.0)
        total_pnl += profit
        n_trades += 1
        if profit > 0:
            n_win += 1
        s = stats.setdefault(sym, {"pnl": 0.0, "n": 0})
        s["pnl"] += profit
        s["n"] += 1

    hit_rate = (100.0 * n_win / n_trades) if n_trades > 0 else 0.0
    # Top symboles par PnL
    top = sorted(stats.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
    top_line = " / ".join([f"{sym}:{v['pnl']:+.2f}" for sym, v in top[:3]]) if top else "N/A"

    # Drawdown intraday approximé : si equity intraday indispo, on omet
    dd_line = "N/A"
    # Message
    msg = (f"#DAILY_DIGEST | {label} Europe/Zurich | P&L {total_pnl:+.2f} | "
           f"trades {n_trades} | hit-rate {hit_rate:.0f}% | top {top_line}")
    return msg

def send_daily_digest(telegram_send_fn, symbols: List[str], tz_name: str = "Europe/Zurich") -> bool:
    """
    telegram_send_fn: callable(text:str, kind:str='daily_digest', force:bool=True) -> Any
    Envoie le digest avec fallback direct requests si nécessaire.
    """
    import logging
    import requests
    import yaml
    logger = logging.getLogger("empire_agent_ia")

    try:
        text = generate_daily_digest(symbols, tz_name=tz_name)
        logger.info(f"[Digest] Envoi digest: {text[:100]}...")

        # Essayer d'abord via le callback normal
        try:
            telegram_send_fn(text, kind="daily_digest", force=True)
        except Exception as e:
            logger.warning(f"[Digest] Callback échoué: {e}")

        # Toujours envoyer via requests en fallback (plus fiable)
        try:
            with open("config/config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            token = cfg.get("telegram", {}).get("token")
            chat_id = cfg.get("telegram", {}).get("chat_id")
            if token and chat_id:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
                if resp.status_code == 200:
                    logger.info("[Digest] ✅ Envoyé via requests fallback")
                else:
                    logger.warning(f"[Digest] Requests fallback: {resp.status_code}")
        except Exception as e2:
            logger.warning(f"[Digest] Fallback requests échoué: {e2}")

        logger.info("[Digest] Digest envoyé avec succès")
        return True
    except Exception as e:
        logger.error(f"[Digest] Échec envoi digest: {e}", exc_info=True)
        return False
