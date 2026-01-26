# utils/telegram_client.py
from __future__ import annotations
from utils.order_result import to_dict as order_res_dict, get as order_res_get
import os
import json
from typing import Any, Dict, List, Optional, Union

import requests
import re
import types
import asyncio
import inspect


try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # on fonctionnera en mode dégradé si PyYAML manque

# Logger optionnel (ne jamais casser le trading si absent)

try:
    from utils.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

try:
    from telegram import Bot as _TelegramBot  # type: ignore
except Exception:  # pragma: no cover
    _TelegramBot = None


class _HttpBot:
    def __init__(self, token: str) -> None:
        self._token = token
        self._base = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id: Union[int, str], text: str, **kwargs: Any):
        payload = {"chat_id": chat_id, "text": text}
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        try:
            resp = requests.post(f"{self._base}/sendMessage", json=payload, timeout=10)
            data = resp.json() if resp.ok else {}
        except Exception:
            data = {}
        message_id = None
        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                message_id = result.get("message_id")
        return types.SimpleNamespace(message_id=message_id, ok=bool(message_id), raw=data)


Bot = _TelegramBot if _TelegramBot is not None else _HttpBot


# ---------------------------------------------------------------------
# Chargement config
# ---------------------------------------------------------------------
_CFG_PATH = os.path.join("config", "config.yaml")


def _load_cfg() -> Dict[str, Any]:
    """
    Lit config/config.yaml et retourne le bloc Telegram utile.
    Structure retournée:
    {
      "enabled": bool,
      "token": str | None,
      "chat_id": int | str | None,
      "allow_kinds": set[str],
      "send_trade_validation_only": bool
    }
    """
    cfg = {}
    try:
        if yaml is None:
            raise RuntimeError("PyYAML indisponible")
        with open(_CFG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}

    tg = cfg.get("telegram") or {}
    # --- Fallback ENV (ne casse jamais en l'absence de YAML) ---
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("token") or tg.get("bot_token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or tg.get("chat_id")

    allow_kinds = tg.get("allow_kinds") or []
    try:
        allow_kinds = set(allow_kinds)
    except Exception:
        allow_kinds = set()

    d = {
        "enabled": bool(tg.get("enabled", True)),
        "token": token,
        "chat_id": chat_id,
        "allow_kinds": allow_kinds,
        "send_trade_validation_only": bool(tg.get("send_trade_validation_only", False)),
    }
    # Normalisation chat_id → int si possible
    try:
        if isinstance(d["chat_id"], str) and d["chat_id"].isdigit():
            d["chat_id"] = int(d["chat_id"])
    except Exception:
        pass
    return d

def _normalize_config(cfg: dict) -> dict:
    tg = (cfg or {}).get("telegram", {}) or {}
    allow = tg.get("allow_kinds") or ["status","trade_validation","news_digest","trade_event","daily_digest"]
    try:
        allow_set = set(allow)
    except Exception:
        allow_set = {"status"}
    allow_set.add("status")
    tg["allow_kinds"] = list(allow_set)
    tg.setdefault("send_trade_validation_only", False)
    return tg

class TelegramClient:
    """Client Telegram synchrone avec compatibilité legacy."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[Union[str, int]] = None, cfg: Optional[Dict[str, Any]] = None, cfg_path: Optional[str] = None):
        base_cfg = dict(_load_cfg())
        if cfg_path and yaml is not None:
            try:
                with open(cfg_path, encoding='utf-8') as f:
                    file_cfg = yaml.safe_load(f) or {}
            except Exception:
                file_cfg = {}
            base_cfg.update(_normalize_config(file_cfg))
        if cfg is not None:
            override = cfg.get('telegram') if isinstance(cfg, dict) and 'telegram' in cfg else cfg
            try:
                base_cfg.update(override or {})
            except Exception:
                pass
        self._cfg = base_cfg
        self.token = token or self._cfg.get('token')
        self.chat_id = chat_id or self._cfg.get('chat_id')
        if isinstance(self.chat_id, str) and self.chat_id.isdigit():
            self.chat_id = int(self.chat_id)
        allow = self._cfg.get('allow_kinds') or set()
        if not isinstance(allow, set):
            try:
                allow = set(allow)
            except Exception:
                allow = set()
        self.allow_kinds = allow
        self.enabled = bool(self._cfg.get('enabled', True))
        self.only_validation = bool(self._cfg.get('send_trade_validation_only', False))
        self.api_base = f"https://api.telegram.org/bot{self.token}" if self.token else None
        self._bot = None
        if self.token:
            try:
                self._bot = Bot(self.token)
            except Exception:
                self._bot = None

    def _should_send(self, kind: str, force: bool) -> bool:
        if force:
            return bool(self.enabled and self.token and self.chat_id)
        if not self.enabled or not self.token or not self.chat_id:
            return False
        if self.only_validation and kind != 'trade_validation':
            return False
        if self.allow_kinds and kind not in self.allow_kinds:
            return False
        return True

    def _post(self, method: str, data: Dict[str, Any]):
        if not (self.enabled and self.api_base and self.chat_id):
            return False
        try:
            url = f"{self.api_base}/{method}"
            response = requests.post(url, json=data, timeout=10)
            payload: Dict[str, Any] = {}
            if response.ok:
                try:
                    payload = response.json()  # type: ignore[assignment]
                except Exception:
                    payload = {}
            message_id = None
            if isinstance(payload, dict):
                result = payload.get('result')
                if isinstance(result, dict):
                    message_id = result.get('message_id')
            return types.SimpleNamespace(message_id=message_id, ok=bool(message_id), raw=payload, status=getattr(response, 'status_code', None))
        except Exception as exc:
            try:
                logger.warning("[TG] HTTP send failed: %s", exc)
            except Exception:
                pass
            return False

    def _build_reply_markup(self, buttons: Optional[List[Dict[str, str]]]):
        if not buttons:
            return None
        if all(isinstance(row, list) for row in buttons):
            keyboard = buttons  # type: ignore[assignment]
        else:
            keyboard = [[{'text': b.get('text', '...'), 'callback_data': b.get('callback_data', '')} for b in buttons]]
        return {'inline_keyboard': keyboard}

    def send_message(self, text: str, *, kind: str = 'status', buttons: Optional[List[Dict[str, str]]] = None, force: bool = False):
        if not self._should_send(kind, force):
            return False
        reply_markup = self._build_reply_markup(buttons)
        if self._bot is not None and reply_markup is None:
            try:
                result = self._bot.send_message(chat_id=self.chat_id, text=text)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        return asyncio.run(result)
                    else:
                        return loop.create_task(result)
                return result
            except Exception as exc:
                try:
                    logger.warning("[TG] Bot send failed, fallback HTTP: %s", exc)
                except Exception:
                    pass
        payload: Dict[str, Any] = {
            'chat_id': self.chat_id,
            'text': text,
            'disable_web_page_preview': True,
            'parse_mode': 'HTML',
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self._post('sendMessage', payload)

    def send_status(self, text: str) -> bool:
        res = self.send_message(text, kind='status')
        return bool(res)

    def send_trade_validation(self, payload: Dict[str, Any]) -> bool:
        if not (self.enabled and self.token and self.chat_id):
            return False
        text = (
            "🟦 <b>Validation de trade</b>\n"
            f"Symbole: <b>{payload.get('symbol')}</b>\n"
            f"Side: <b>{payload.get('side')}</b>\n"
            f"Entrée: <code>{payload.get('entry')}</code>\n"
            f"SL: <code>{payload.get('sl')}</code> | TP: <code>{payload.get('tp') or payload.get('tp1')}</code>\n"
            f"R:R: <code>{payload.get('rr')}</code> | Taille: <code>{payload.get('size')}</code>\n"
            f"Expire: <i>{payload.get('expiry_local')}</i>"
        )
        reply_markup = {
            'inline_keyboard': [[
                {'text': '✅ Valider', 'callback_data': json.dumps({'action': 'CONFIRM', 'payload': payload})},
                {'text': '❌ Rejeter', 'callback_data': json.dumps({'action': 'REJECT', 'payload': payload})},
            ]]
        }
        data = {
            'chat_id': self.chat_id,
            'text': text,
            'disable_web_page_preview': True,
            'parse_mode': 'HTML',
            'reply_markup': reply_markup,
        }
        res = self._post('sendMessage', data)
        return bool(res)

# ---------------------------------------------------------------------
# Fonction simple (stateless) pour envoyer un message
# ---------------------------------------------------------------------

def send_message(
    text: str,
    *,
    kind: str = "status",
    force: bool = False,
    buttons: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """Compat wrapper utilisant TelegramClient."""
    client = TelegramClient()
    res = client.send_message(text, kind=kind, buttons=buttons, force=force)
    return bool(res)

_t = send_message
_tg = send_message

def send_telegram_message(*args, **kwargs) -> bool:
    text = kwargs.pop('text', None)
    if text is None and args:
        text = args[0]
        args = args[1:]
    kind = kwargs.pop('kind', 'status')
    force = bool(kwargs.pop('force', False))
    buttons = kwargs.pop('buttons', None)
    if text is None:
        return False
    client = TelegramClient()
    res = client.send_message(text, kind=kind, buttons=buttons, force=force)
    return bool(res)




# ---------------------------------------------------------------------
# Variante asynchrone minimale (shim)
# ---------------------------------------------------------------------
class AsyncTelegramClient:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[Union[str, int]] = None, cfg: Optional[Dict[str, Any]] = None):
        self.sync = TelegramClient(token=token, chat_id=chat_id, cfg=cfg)

    async def send_message(self, text: str, *, kind: str = "status", buttons: Optional[List[Dict[str, str]]] = None, force: bool = False) -> bool:
        return bool(self.sync.send_message(text, kind=kind, buttons=buttons, force=force))

    async def send_trade_validation(self, payload: Dict[str, Any]) -> bool:
        return bool(self.sync.send_trade_validation(payload))

    async def send_status(self, text: str) -> bool:
        return bool(self.sync.send_status(text))
