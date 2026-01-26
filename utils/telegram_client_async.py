from aiogram import Bot, Dispatcher, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramConflictError
import logging
import asyncio
import yaml
from typing import Optional, Iterable
import json
import os
import sys
import requests

class AsyncTelegramClient:
    """
    Client Telegram optimisé:
    - Envoi via requests (plus fiable, pas de timeout)
    - aiogram uniquement pour recevoir les callbacks (boutons)
    - Filtrage par kind pour réduire le spam
    """
    DEFAULT_ALLOWED_KINDS = {"trade_validation", "news_digest", "status", "daily_digest"}

    def __init__(self, token: str | None, chat_id: str | int | None, orchestrator=None):
        token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        try:
            if isinstance(chat_id, str) and chat_id.isdigit():
                chat_id = int(chat_id)
        except Exception:
            pass
        self.token = token
        self.chat_id = chat_id

        if not self.token:
            raise RuntimeError("AsyncTelegramClient: TELEGRAM_BOT_TOKEN manquant.")
        if not self.chat_id:
            raise RuntimeError("AsyncTelegramClient: TELEGRAM_CHAT_ID manquant.")

        # Bot pour les callbacks uniquement
        self.bot = Bot(token=self.token, default=DefaultBotProperties(parse_mode='HTML'))
        self.dp = Dispatcher()
        self.logger = logging.getLogger("AsyncTelegramClient")
        self.orchestrator = orchestrator

        self._cfg = self._load_cfg()
        cfg_kinds = set((self._cfg.get("telegram", {}) or {}).get("allow_kinds", []) or [])
        self.allowed_kinds = (cfg_kinds | self.DEFAULT_ALLOWED_KINDS)

        self._register_handlers()

    @staticmethod
    def _load_cfg() -> dict:
        try:
            return yaml.safe_load(open("config/config.yaml", encoding="utf-8")) or {}
        except Exception:
            return {}

    def _reload_cfg(self):
        self._cfg = self._load_cfg()
        cfg_kinds = set((self._cfg.get("telegram", {}) or {}).get("allow_kinds", []) or [])
        self.allowed_kinds = (cfg_kinds | self.DEFAULT_ALLOWED_KINDS)

    # ------------------- Envoi messages (requests uniquement) -------------------
    async def send_message(self, text: str, buttons: Optional[Iterable[dict]] = None,
                           kind: Optional[str] = None, force: bool = False) -> bool:
        """Envoie un message Telegram via requests (plus fiable)."""
        self._reload_cfg()

        push_only_on_master = (self._cfg.get("orchestrator", {}) or {}).get("push_only_on_master", True)
        news_digest_enabled = ((self._cfg.get("news", {}) or {}).get("digest", {}) or {}).get("enabled", True)

        # Filtrage
        if not force:
            allowed = False
            if kind is None:
                allowed = True
            else:
                if kind in self.allowed_kinds:
                    allowed = True
                if kind == "trade_validation":
                    allowed = True
                elif kind == "news_digest" and news_digest_enabled:
                    allowed = True
                if not allowed and not push_only_on_master:
                    allowed = True

            if not allowed:
                return True  # Filtré silencieusement

        # Envoi via requests (synchrone mais dans un thread pour ne pas bloquer)
        return await asyncio.to_thread(self._send_sync, text, buttons)

    def _send_sync(self, text: str, buttons: Optional[Iterable[dict]] = None) -> bool:
        """Envoi synchrone via requests."""
        try:
            url = f'https://api.telegram.org/bot{self.token}/sendMessage'
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }

            # Ajouter les boutons si présents
            if buttons:
                keyboard = [[{"text": b['text'], "callback_data": b['callback_data']}] for b in buttons]
                payload['reply_markup'] = json.dumps({"inline_keyboard": keyboard})

            resp = requests.post(url, json=payload, timeout=30)
            return resp.status_code == 200
        except Exception as e:
            self.logger.error(f"[TG] Erreur envoi: {e}")
            return False

    # ------------------- Handlers (pour boutons) -------------------
    def _register_handlers(self):
        @self.dp.callback_query(lambda c: c.data and c.data.startswith("validate_trade_"))
        async def on_validate_trade(callback_query: types.CallbackQuery):
            signal = callback_query.data.split("_")[-1]
            try:
                await callback_query.answer("✅ Trade validé!", show_alert=True)
            except Exception:
                pass

            if self.orchestrator:
                try:
                    await self.orchestrator.execute_trade(signal)
                except Exception as e:
                    self.logger.error(f"Erreur exécution trade: {e}")

            await self.send_message(f"🚀 Trade {signal} exécuté!", kind="trade_validation", force=True)

        @self.dp.callback_query(lambda c: c.data and c.data.startswith("reject_trade_"))
        async def on_reject_trade(callback_query: types.CallbackQuery):
            try:
                await callback_query.answer("❌ Trade rejeté.", show_alert=False)
            except Exception:
                pass

            if self.orchestrator and hasattr(self.orchestrator, "_last_proposal"):
                self.orchestrator._last_proposal = None

            await self.send_message("❌ Trade rejeté.", kind="trade_validation", force=True)

        @self.dp.callback_query(lambda c: c.data and c.data.startswith("{") and c.data.endswith("}"))
        async def on_json_action(callback_query: types.CallbackQuery):
            try:
                payload = json.loads(callback_query.data)
            except Exception:
                return

            action = (payload.get("action") or "").upper()
            direction = (payload.get("direction") or "").upper()

            if action == "CONFIRM":
                if not direction and self.orchestrator and getattr(self.orchestrator, "_last_proposal", None):
                    direction = (self.orchestrator._last_proposal.get("side") or "").upper()

                if direction not in ("LONG", "SHORT"):
                    await callback_query.answer("⚠️ Direction inconnue.", show_alert=True)
                    return

                await callback_query.answer("✅ Trade validé!", show_alert=True)

                if self.orchestrator:
                    await self.orchestrator.execute_trade(direction)

                await self.send_message(f"🚀 Trade {direction} exécuté!", kind="trade_validation", force=True)

            elif action == "REJECT":
                await callback_query.answer("❌ Trade rejeté.", show_alert=False)
                if self.orchestrator and hasattr(self.orchestrator, "_last_proposal"):
                    self.orchestrator._last_proposal = None
                await self.send_message("❌ Trade rejeté.", kind="trade_validation", force=True)

    # ------------------- Boucle bot (callbacks uniquement) -------------------
    async def run(self):
        """
        Démarre le polling pour recevoir les callbacks Telegram.
        Gère proprement le TelegramConflictError (plusieurs instances).
        """
        self.logger.info("[TG] Démarrage polling callbacks")

        # Supprimer le webhook au démarrage (conflit potentiel)
        try:
            await self.bot.delete_webhook(drop_pending_updates=True)
            self.logger.info("[TG] ✅ Webhook supprimé, pending updates nettoyés")
        except Exception as e:
            self.logger.warning(f"[TG] Impossible de supprimer le webhook: {e}")

        try:
            await self.dp.start_polling(self.bot)
        except TelegramConflictError as e:
            self.logger.critical(
                f"\n"
                f"{'='*60}\n"
                f"❌ ERREUR CRITIQUE: CONFLIT TELEGRAM DÉTECTÉ!\n"
                f"{'='*60}\n"
                f"Message: {e}\n"
                f"\n"
                f"CAUSE: Une autre instance du bot est déjà en cours d'exécution.\n"
                f"\n"
                f"SOLUTION:\n"
                f"  1. Listez les processus: pgrep -af 'python.*main.py'\n"
                f"  2. Tuez les doublons:    pkill -f 'python.*main.py'\n"
                f"  3. Relancez le bot\n"
                f"{'='*60}"
            )
            # Arrêt propre au lieu de boucler indéfiniment
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"[TG] Polling stoppé: {e}")
