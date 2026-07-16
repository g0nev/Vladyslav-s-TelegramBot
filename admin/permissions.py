from __future__ import annotations

from aiogram import Bot

ADMIN_STATUSES = {"administrator", "creator"}


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ADMIN_STATUSES
