from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions

from moderation.actions import kick_user, mute_user


async def test_mute_user_restricts_and_returns_true():
    bot = AsyncMock()

    result = await mute_user(bot, chat_id=1, user_id=100, minutes=10)

    assert result is True
    bot.restrict_chat_member.assert_awaited_once()
    kwargs = bot.restrict_chat_member.await_args.kwargs
    assert isinstance(kwargs["permissions"], ChatPermissions)
    assert kwargs["permissions"].can_send_messages is False
    assert kwargs["until_date"] is not None


async def test_mute_user_returns_false_on_api_error():
    bot = AsyncMock()
    bot.restrict_chat_member.side_effect = TelegramAPIError(method=None, message="no rights")

    result = await mute_user(bot, chat_id=1, user_id=100, minutes=5)

    assert result is False


async def test_kick_user_bans_then_unbans_and_returns_true():
    bot = AsyncMock()

    result = await kick_user(bot, chat_id=1, user_id=100)

    assert result is True
    bot.ban_chat_member.assert_awaited_once()
    bot.unban_chat_member.assert_awaited_once()


async def test_kick_user_returns_false_on_api_error():
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = TelegramAPIError(method=None, message="no rights")

    result = await kick_user(bot, chat_id=1, user_id=100)

    assert result is False
    bot.unban_chat_member.assert_not_awaited()
