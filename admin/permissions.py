from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message

ADMIN_STATUSES = {"administrator", "creator"}


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ADMIN_STATUSES


async def require_admin(message: Message, bot: Bot) -> bool:
    if message.from_user is None:
        return False
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("Эта команда доступна только администраторам чата.")
        return False
    return True
