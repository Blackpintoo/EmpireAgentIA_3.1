"""Runtime launcher for EmpireAgentIA."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import subprocess

from orchestrator.orchestrator import Orchestrator
from utils.config import get_enabled_symbols, load_config, get_overrides
from utils.digest import TZ
from utils.logger import logger
from utils.telegram_client_async import AsyncTelegramClient
from utils.telegram_client import send_telegram_message


def _load_yaml(path: Path) -> Dict[str, any]:
    if not path.exists():
        return {}
    import yaml
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _resolve_symbols(cfg: Dict[str, any], cli_symbols: Optional[Iterable[str]]) -> List[str]:
    if cli_symbols:
        return [s.upper() for s in cli_symbols]
    symbols = get_enabled_symbols()
    if symbols:
        return symbols
    agents_cfg = (cfg.get("agents") or [])
    return [entry.get("symbol", "BTCUSD").upper() for entry in agents_cfg] or ["BTCUSD"]


def _load_proposal(path: Path) -> Tuple[Optional[Dict[str, any]], Optional[str]]:
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[launcher] Impossible de lire {path}: {exc}")
        return None, None
    signature = raw.get("id") or raw.get("hash") or raw.get("timestamp") or str(path.stat().st_mtime_ns)
    payload = {
        "symbol": raw.get("symbol"),
        "side": raw.get("side"),
        "entry": raw.get("entry"),
        "sl": raw.get("sl"),
        "tp": raw.get("tp"),
        "lots": raw.get("lots"),
        "score": raw.get("score"),
        "confluence": raw.get("confluence"),
    }
    return payload, signature


async def _proposal_watcher(orch: Orchestrator, proposal_dir: Path, poll_seconds: float) -> None:
    path = proposal_dir / f"{orch.symbol}.json"
    last_signature: Optional[str] = None
    logger.info("[launcher] Watcher %s -> %s", orch.symbol, path)
    while True:
        try:
            payload, signature = _load_proposal(path)
            if payload and signature and signature != last_signature:
                proposal = orch._build_proposal(payload)
                if proposal:
                    await orch.execute_trade(proposal.get("side"))
                    last_signature = signature
        except Exception as exc:
            logger.exception(f"[launcher] watcher {orch.symbol} erreur: {exc}")
        await asyncio.sleep(max(1.0, poll_seconds))


async def _daily_digest_loop(orchestrators: List[Orchestrator]) -> None:
    sent_slots: Dict[str, Dict[str, set]] = {}
    while True:
        try:
            now_local = datetime.now(TZ)
            today = now_local.strftime("%Y-%m-%d")
            current_slot = now_local.strftime("%H:%M")
            for orch in orchestrators:
                if hasattr(orch.__class__, "_digest_scheduler"):
                    continue
                tg_cfg = (orch.cfg or {}).get("telegram", {}) or {}
                if not bool(tg_cfg.get("send_daily_digest", False)):
                    continue

                raw_times = tg_cfg.get("daily_digest_times")
                if isinstance(raw_times, (list, tuple, set)):
                    slots = [str(t).strip() for t in raw_times if str(t).strip()]
                elif raw_times:
                    slots = [str(raw_times)]
                else:
                    slots = [str(tg_cfg.get("daily_digest_time", "19:00"))]

                if current_slot not in slots:
                    continue

                entry = sent_slots.setdefault(orch.symbol, {"date": today, "slots": set()})
                if entry["date"] != today:
                    entry["date"] = today
                    entry["slots"] = set()

                if current_slot in entry["slots"]:
                    continue

                if orch._send_daily_digest():  # type: ignore[attr-defined]
                    entry["slots"].add(current_slot)
        except Exception as exc:
            logger.exception(f"[launcher] daily digest erreur: {exc}")
        await asyncio.sleep(60)


async def _telegram_runtime(client: AsyncTelegramClient) -> None:
    try:
        await client.run()
    except Exception as exc:
        logger.exception(f"[launcher] Telegram runtime erreur: {exc}")


def _parse_time_string(value: str, fallback: str) -> dtime:
    for candidate in (value, fallback):
        try:
            hh, mm = [int(x) for x in candidate.strip().split(":")]
            return dtime(int(hh), int(mm))
        except Exception:
            continue
    return dtime(0, 0)


def _is_process_running(process_name: str) -> bool:
    if not process_name:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return process_name.lower() in (result.stdout or "").lower()
    except Exception as exc:
        logger.warning(f"[mt5] tasklist failed: {exc}")
        return False


def _start_mt5_terminal(executable: Path) -> None:
    try:
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        subprocess.Popen(
            [str(executable)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        logger.info("[mt5] terminal lancé: %s", executable)
    except Exception as exc:
        logger.error(f"[mt5] lancement terminal impossible ({executable}): {exc}")


def _stop_mt5_terminal(process_name: str) -> None:
    if not process_name:
        return
    try:
        subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        logger.info("[mt5] terminal arrêté (%s)", process_name)
    except Exception as exc:
        logger.warning(f"[mt5] arrêt terminal impossible ({process_name}): {exc}")


def _should_mt5_run(now: datetime, monday_start: dtime, friday_stop: dtime) -> bool:
    weekday = now.weekday()
    current_time = now.time()
    if weekday in (5, 6):
        return False
    if weekday == 4 and current_time >= friday_stop:
        return False
    if weekday == 0 and current_time < monday_start:
        return False
    return True


async def _mt5_guard_loop(cfg: Dict[str, str]) -> None:
    terminal_path = Path(cfg["terminal_path"]).expanduser()
    if not terminal_path.exists():
        logger.warning("[mt5] terminal introuvable: %s", terminal_path)
        return
    process_name = cfg.get("process_name") or terminal_path.name
    monday_start = _parse_time_string(cfg.get("monday_start", "00:05"), "00:05")
    friday_stop = _parse_time_string(cfg.get("friday_stop", "23:00"), "23:00")
    interval = max(60, int(cfg.get("check_interval_minutes", 5)) * 60)
    logger.info("[mt5] garde terminal active (process=%s)", process_name)
    while True:
        try:
            now = datetime.now(TZ)
            desired = _should_mt5_run(now, monday_start, friday_stop)
            running = _is_process_running(process_name)
            if desired and not running:
                _start_mt5_terminal(terminal_path)
            elif not desired and running:
                _stop_mt5_terminal(process_name)
        except Exception as exc:
            logger.warning(f"[mt5] boucle garde erreur: {exc}")
        await asyncio.sleep(interval)


async def _runtime(orchestrators: List[Orchestrator], proposal_dir: Path, poll_seconds: float,
                   telegram_client: Optional[AsyncTelegramClient],
                   mt5_guard_cfg: Optional[Dict[str, str]]) -> None:
    tasks = []
    for orch in orchestrators:
        tasks.append(asyncio.create_task(_proposal_watcher(orch, proposal_dir, poll_seconds)))
    tasks.append(asyncio.create_task(_daily_digest_loop(orchestrators)))
    if telegram_client is not None:
        tasks.append(asyncio.create_task(_telegram_runtime(telegram_client)))
    if mt5_guard_cfg:
        tasks.append(asyncio.create_task(_mt5_guard_loop(mt5_guard_cfg)))
    await asyncio.gather(*tasks)


def build_orchestrators(symbols: Iterable[str], *, cfg: Dict[str, any], dry_run: bool,
                        overrides_path: Optional[str], telegram_client: Optional[AsyncTelegramClient]) -> List[Orchestrator]:
    orchestrators: List[Orchestrator] = []
    # FIX 2026-02-24: Charger overrides pour vérifier enabled (Directive 9)
    _ov = get_overrides() or {}
    for symbol in symbols:
        # FIX 2026-02-24: Skip symboles désactivés dans overrides.yaml
        _sym_ov = (_ov.get(symbol, {}) or {}).get("orchestrator", {}) or {}
        if _sym_ov.get("enabled") is False:
            logger.info("[DISABLED] Symbole %s désactivé dans overrides.yaml — skip", symbol)
            continue
        orch = Orchestrator(symbol=symbol, cfg=cfg, dry_run=dry_run,
                            telegram_client=telegram_client, overrides_path=overrides_path)
        orchestrators.append(orch)
        logger.info("[launcher] Orchestrator prêt pour %s (dry=%s)", symbol, orch.dry_run)
    return orchestrators


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("EmpireAgentIA runtime launcher")
    parser.add_argument("--symbols", nargs="*", help="Liste des symboles à lancer (défaut: config/profiles)")
    parser.add_argument("--config", default="config/config.yaml", help="Chemin vers le fichier config")
    parser.add_argument("--overrides", help="Fichier overrides YAML à appliquer")
    parser.add_argument("--proposal-dir", default="data/proposals", help="Répertoire des propositions JSON")
    parser.add_argument("--poll", type=float, default=5.0, help="Période de scan des propositions (secondes)")
    parser.add_argument("--dry-run", action="store_true", help="Active le mode dry-run")
    parser.add_argument("--no-telegram", action="store_true", help="Désactive le client Telegram asynchrone")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = _load_yaml(Path(args.config))
    symbols = _resolve_symbols(cfg, args.symbols)

    os.makedirs(args.proposal_dir, exist_ok=True)
    proposal_dir = Path(args.proposal_dir)

    telegram_client: Optional[AsyncTelegramClient] = None
    if not args.no_telegram:
        tg_cfg = cfg.get("telegram") or {}
        telegram_client = AsyncTelegramClient(tg_cfg.get("token"), tg_cfg.get("chat_id"))

    mt5_cfg = cfg.get("mt5") or {}
    autostart_cfg = mt5_cfg.get("autostart") or {}
    mt5_guard_cfg: Optional[Dict[str, str]] = None
    if bool(autostart_cfg.get("enabled", False)):
        terminal_path = autostart_cfg.get("terminal_path") or mt5_cfg.get("terminal_path")
        if terminal_path:
            mt5_guard_cfg = {
                "terminal_path": terminal_path,
                "process_name": autostart_cfg.get("process_name") or Path(terminal_path).name,
                "monday_start": str(autostart_cfg.get("monday_start", "00:05")),
                "friday_stop": str(autostart_cfg.get("friday_stop", "23:00")),
                "check_interval_minutes": str(autostart_cfg.get("check_interval_minutes", 5)),
            }
        else:
            logger.warning("[mt5] autostart activé mais aucun terminal_path n'est défini.")

    orchestrators = build_orchestrators(symbols, cfg=cfg, dry_run=args.dry_run,
                                        overrides_path=args.overrides, telegram_client=telegram_client)
    logger.info("[launcher] Empire démarré pour %s", symbols)

    if not args.no_telegram:
        try:
            send_telegram_message(text="🚀 Empire Agent IA démarré (mode réel).", kind="startup", force=True)
        except Exception as exc:
            logger.warning(f"[launcher] telegram confirmation échouée: {exc}")

    try:
        asyncio.run(_runtime(orchestrators, proposal_dir, args.poll, telegram_client, mt5_guard_cfg))
    except KeyboardInterrupt:
        logger.info("[launcher] arrêt demandé par l’utilisateur")
        if not args.no_telegram:
            try:
                msg = "🛑 Empire Agent IA arrêté manuellement." if not args.dry_run else "🛑 Empire Agent IA (dry-run) arrêté manuellement."
                send_telegram_message(text=msg, kind="shutdown", force=True)
            except Exception as exc:
                logger.warning(f"[launcher] telegram shutdown échoué: {exc}")


if __name__ == "__main__":
    main()
