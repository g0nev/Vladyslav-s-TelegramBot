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

    try:
        client = TelegramClient(
            StringSession(config.TELETHON_SESSION_STRING),
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
        )
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(
                "Telethon session is not authorized; chat history reading is disabled."
            )
            await client.disconnect()
            return None

        try:
            # Warm the entity cache so the first iter_messages() call on a
            # fresh session doesn't need to resolve the peer over the
            # network (which can fail for channels the userbot hasn't
            # "seen" yet this session). Non-critical: the client is still
            # usable without it, just with more first-call risk.
            await client.get_dialogs()
        except Exception:
            logger.warning("Failed to warm Telethon entity cache; continuing without it.")

        return client
    except Exception:
        logger.exception(
            "Failed to start Telethon userbot client; chat history reading is disabled."
        )
        return None
