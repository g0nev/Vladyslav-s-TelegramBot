from __future__ import annotations

import uuid
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from admin.permissions import is_admin
from ai.content_filter import check_hard_block
from ai.openrouter_client import AIUnavailableError, ask_ai_with_tools
from ai.tools import (
    ADMIN_TOOL_NAMES,
    ADMIN_TOOLS,
    CONFIRMATION_TOOLS,
    PUBLIC_TOOL_NAMES,
    PUBLIC_TOOLS,
    TARGET_REQUIRED_TOOLS,
    execute_tool,
)
from db.repository import Repository
from moderation.actions import kick_user, mute_user

router = Router(name="ai")

BLOCK_MESSAGE = "Не могу выполнить этот запрос."
UNAVAILABLE_MESSAGE = "ИИ временно недоступен, попробуй позже."
TARGET_REQUIRED_MESSAGE = (
    "Ответьте на сообщение нужного человека, чтобы я выполнил это действие."
)
NOT_YOUR_DECISION_MESSAGE = "Это решение может подтвердить только тот, кто вызвал /ask."
EXPIRED_MESSAGE = "Это подтверждение больше не действительно."
NO_RIGHTS_MESSAGE = "Не удалось: боту не хватает прав."
CANCELLED_MESSAGE = "Действие отменено."


@dataclass
class PendingAction:
    admin_user_id: int
    chat_id: int
    action: str  # "mute" or "kick"
    target_user_id: int
    target_mention: str
    minutes: int


_pending_actions: dict[str, PendingAction] = {}


def _extract_minutes(arguments: dict) -> int:
    try:
        minutes = int(arguments.get("minutes", 5))
    except (TypeError, ValueError):
        minutes = 5
    return minutes if minutes > 0 else 5


@router.message(Command("ask"))
async def cmd_ask(
    message: Message,
    command: CommandObject,
    bot: Bot,
    repository: Repository,
    scheduler: AsyncIOScheduler,
) -> None:
    if not command.args or not command.args.strip():
        await message.answer(
            "Добрый день! Вы хотели ко мне обратиться? Тогда напишите /ask <вопрос>."
        )
        return

    question = command.args.strip()

    if message.from_user is None:
        return

    if check_hard_block(question):
        await message.answer(BLOCK_MESSAGE)
        return

    admin = await is_admin(bot, message.chat.id, message.from_user.id)
    tools = ADMIN_TOOLS if admin else PUBLIC_TOOLS
    allowed_names = ADMIN_TOOL_NAMES if admin else PUBLIC_TOOL_NAMES

    reply = message.reply_to_message
    target_id = reply.from_user.id if reply and reply.from_user else None
    target_mention = reply.from_user.mention_html() if reply and reply.from_user else None

    try:
        response = await ask_ai_with_tools(question, tools)
    except AIUnavailableError:
        await message.answer(UNAVAILABLE_MESSAGE)
        return

    if response.tool_name is None:
        await message.answer(response.text or UNAVAILABLE_MESSAGE, parse_mode="Markdown")
        return

    tool_name = response.tool_name

    if tool_name not in allowed_names:
        await message.answer(BLOCK_MESSAGE)
        return

    if tool_name in TARGET_REQUIRED_TOOLS and target_id is None:
        await message.answer(TARGET_REQUIRED_MESSAGE)
        return

    if tool_name in CONFIRMATION_TOOLS:
        minutes = _extract_minutes(response.tool_arguments)
        token = uuid.uuid4().hex
        _pending_actions[token] = PendingAction(
            admin_user_id=message.from_user.id,
            chat_id=message.chat.id,
            action="mute" if tool_name == "mute_user" else "kick",
            target_user_id=target_id,
            target_mention=target_mention,
            minutes=minutes,
        )
        if tool_name == "mute_user":
            prompt = f"Замьютить {target_mention} на {minutes} мин.?"
        else:
            prompt = f"Удалить {target_mention} из чата?"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да", callback_data=f"aiconfirm:{token}:yes"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отмена", callback_data=f"aiconfirm:{token}:no"
                    ),
                ]
            ]
        )
        await message.answer(prompt, reply_markup=keyboard)
        return

    result = await execute_tool(
        tool_name,
        response.tool_arguments,
        bot=bot,
        repository=repository,
        scheduler=scheduler,
        chat_id=message.chat.id,
        target_id=target_id,
        target_mention=target_mention,
    )
    await message.answer(result)


@router.callback_query(F.data.startswith("aiconfirm:"))
async def on_ai_confirm(callback: CallbackQuery, bot: Bot) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, token, decision = parts

    pending = _pending_actions.get(token)
    if pending is None:
        await callback.answer(EXPIRED_MESSAGE, show_alert=True)
        return

    if callback.from_user.id != pending.admin_user_id:
        await callback.answer(NOT_YOUR_DECISION_MESSAGE, show_alert=True)
        return

    _pending_actions.pop(token, None)

    if decision == "no":
        await callback.message.edit_text(CANCELLED_MESSAGE)
        await callback.answer()
        return

    if pending.action == "mute":
        ok = await mute_user(
            bot, pending.chat_id, pending.target_user_id, pending.minutes
        )
        text = (
            f"{pending.target_mention} замьючен на {pending.minutes} мин."
            if ok
            else NO_RIGHTS_MESSAGE
        )
    else:
        ok = await kick_user(bot, pending.chat_id, pending.target_user_id)
        text = f"{pending.target_mention} удалён из чата." if ok else NO_RIGHTS_MESSAGE

    await callback.message.edit_text(text)
    await callback.answer()
