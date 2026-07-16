from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.filters import CommandObject

from ai.handlers import cmd_ask


def make_message():
    return SimpleNamespace(answer=AsyncMock())


def cmd(args):
    return CommandObject(prefix="/", command="ask", args=args)


async def test_ask_without_args_shows_usage():
    message = make_message()

    await cmd_ask(message, cmd(None))

    message.answer.assert_awaited_once_with("Использование: /ask <вопрос>")


async def test_ask_returns_ai_answer():
    message = make_message()

    with patch("ai.handlers.ask_ai", AsyncMock(return_value="42")):
        await cmd_ask(message, cmd("Смысл жизни?"))

    message.answer.assert_awaited_once_with("42")


async def test_ask_reports_when_ai_unavailable():
    from ai.openrouter_client import AIUnavailableError

    message = make_message()

    with patch("ai.handlers.ask_ai", AsyncMock(side_effect=AIUnavailableError("boom"))):
        await cmd_ask(message, cmd("Привет"))

    message.answer.assert_awaited_once_with("ИИ временно недоступен, попробуй позже.")
