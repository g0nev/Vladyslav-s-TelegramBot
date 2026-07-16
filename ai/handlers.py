from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ai.openrouter_client import AIUnavailableError, ask_ai

router = Router(name="ai")


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.strip():
        await message.answer("Использование: /ask <вопрос>")
        return

    try:
        answer = await ask_ai(command.args.strip())
    except AIUnavailableError:
        await message.answer("ИИ временно недоступен, попробуй позже.")
        return

    await message.answer(answer)
