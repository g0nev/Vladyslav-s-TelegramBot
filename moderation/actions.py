from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions


async def mute_user(bot: Bot, chat_id: int, user_id: int, minutes: int) -> bool:
    until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
    except TelegramAPIError:
        return False
    return True


async def kick_user(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except TelegramAPIError:
        return False
    return True
