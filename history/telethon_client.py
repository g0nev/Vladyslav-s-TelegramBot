from __future__ import annotations

import logging
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

import config

logger = logging.getLogger(__name__)


async def start_client() -> Optional[TelegramClient]:
    """Connect the userbot client used for on-demand chat history reads.

    Returns None (without raising) whenever Telethon isn't configured or the
    stored session is no longer valid — callers must treat a None client as
    "chat history reading is unavailable", not as an error.
    """
    if not (
        config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH and config.TELETHON_SESSION_STRING
    ):
        logger.info("Telethon userbot is not configured; chat history reading is disabled.")
        return None

    client = TelegramClient(
        StringSession(config.TELETHON_SESSION_STRING),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    await client.connect()
    if not await client.is_user_authorized():
        logger.warning("Telethon session is not authorized; chat history reading is disabled.")
        await client.disconnect()
        return None
    return client
