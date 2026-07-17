from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message

from admin.permissions import is_admin
from db.repository import Repository
from moderation.logic import (
    compute_violation,
    contains_trigger_word,
    format_punishment_message,
    merge_trigger_words,
)

router = Router(name="moderation")

MUTE_MINUTES = 5

WARN_TEMPLATES = {
    "warn": "{mention}, предупреждение: сообщение нарушает правила чата.",
    "mute": "{mention} получает ограничение на отправку сообщений на {minutes} минут "
    "за повторное нарушение.",
    "kick": "{mention} удаляется из чата за повторные нарушения. "
    "Вернуться можно по новой ссылке-приглашению.",
}

PERMISSION_NOTICE_COOLDOWN = timedelta(minutes=10)
_last_permission_notice: dict[int, datetime] = {}


def _mention(message: Message) -> str:
    return message.from_user.mention_html()


async def _notify_missing_permissions(message: Message) -> None:
    now = datetime.now(timezone.utc)
    last_notice = _last_permission_notice.get(message.chat.id)
    if last_notice is not None and now - last_notice < PERMISSION_NOTICE_COOLDOWN:
        return
    _last_permission_notice[message.chat.id] = now
    await message.answer(
        "Боту не хватает прав администратора, чтобы ограничивать/удалять участников."
    )


async def handle_moderated_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    if message.from_user is None or message.text is None:
        return

    if await is_admin(bot, message.chat.id, message.from_user.id):
        return

    db_words = await repository.list_trigger_words(message.chat.id)
    trigger_words = merge_trigger_words(default_trigger_words, db_words)

    if not contains_trigger_word(message.text, trigger_words):
        return

    count, last_violation_at_raw = await repository.get_warning(
        message.chat.id, message.from_user.id
    )
    _, reset_days = await repository.get_chat_settings(message.chat.id)

    last_violation_at = (
        datetime.fromisoformat(last_violation_at_raw) if last_violation_at_raw else None
    )
    now = datetime.now(timezone.utc)

    new_count, punishment = compute_violation(count, last_violation_at, reset_days, now)

    if punishment == "mute":
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=now + timedelta(minutes=MUTE_MINUTES),
            )
        except TelegramAPIError:
            await _notify_missing_permissions(message)
            return
    elif punishment == "kick":
        try:
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            await bot.unban_chat_member(message.chat.id, message.from_user.id, only_if_banned=True)
        except TelegramAPIError:
            await _notify_missing_permissions(message)
            return

    # Only persist the new count once the enforcement action (if any) has
    # actually succeeded, so a permission failure doesn't silently advance
    # or reset the user's violation history.
    await repository.set_warning(
        message.chat.id, message.from_user.id, new_count, now.isoformat()
    )

    warn_message, mute_message, kick_message = await repository.get_message_templates(
        message.chat.id
    )
    custom_template = {"warn": warn_message, "mute": mute_message, "kick": kick_message}[
        punishment
    ]
    template = custom_template if custom_template else WARN_TEMPLATES[punishment]
    text = format_punishment_message(
        html.escape(template, quote=False), mention=_mention(message), minutes=MUTE_MINUTES
    )
    await message.answer(text)


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def on_group_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    await handle_moderated_message(message, bot, repository, default_trigger_words)
