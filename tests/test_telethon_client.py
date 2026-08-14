from unittest.mock import AsyncMock, patch

import config
from history.telethon_client import start_client


async def test_start_client_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_API_ID", 0)
    monkeypatch.setattr(config, "TELEGRAM_API_HASH", "")
    monkeypatch.setattr(config, "TELETHON_SESSION_STRING", "")

    result = await start_client()

    assert result is None


async def test_start_client_returns_none_when_session_unauthorized(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_API_ID", 123)
    monkeypatch.setattr(config, "TELEGRAM_API_HASH", "hash")
    monkeypatch.setattr(config, "TELETHON_SESSION_STRING", "session")

    fake_client = AsyncMock()
    fake_client.connect = AsyncMock()
    fake_client.is_user_authorized = AsyncMock(return_value=False)
    fake_client.disconnect = AsyncMock()

    with patch("history.telethon_client.TelegramClient", return_value=fake_client), patch(
        "history.telethon_client.StringSession"
    ):
        result = await start_client()

    assert result is None
    fake_client.connect.assert_awaited_once()
    fake_client.disconnect.assert_awaited_once()


async def test_start_client_returns_client_when_authorized(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_API_ID", 123)
    monkeypatch.setattr(config, "TELEGRAM_API_HASH", "hash")
    monkeypatch.setattr(config, "TELETHON_SESSION_STRING", "session")

    fake_client = AsyncMock()
    fake_client.connect = AsyncMock()
    fake_client.is_user_authorized = AsyncMock(return_value=True)

    with patch("history.telethon_client.TelegramClient", return_value=fake_client), patch(
        "history.telethon_client.StringSession"
    ):
        result = await start_client()

    assert result is fake_client
