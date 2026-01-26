# tests/test_telegram_client.py
import sys
import os
import types
# 1. Ajouter la racine du projet au Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# 2. Stub 'imghdr' pour éviter les erreurs d'import dans python-telegram-bot
sys.modules['imghdr'] = types.ModuleType('imghdr')

import pytest
from unittest.mock import MagicMock, patch
from utils.telegram_client import TelegramClient

@patch('utils.telegram_client.Bot')
def test_send_message(mock_bot_cls):
    # Simuler l'API Telegram
    mock_bot = MagicMock()
    mock_bot.send_message.return_value = MagicMock(message_id=123)
    mock_bot_cls.return_value = mock_bot

    # Instancier et appeler
    tg = TelegramClient(cfg_path='config/config.yaml')
    res = tg.send_message("Hello Empire")

    # Vérifier l'appel et le retour
    mock_bot.send_message.assert_called_once_with(
        chat_id=tg.chat_id,
        text="Hello Empire"
    )
    assert hasattr(res, 'message_id') and res.message_id == 123