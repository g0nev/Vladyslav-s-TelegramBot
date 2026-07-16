from types import SimpleNamespace
from unittest.mock import AsyncMock

from admin.permissions import is_admin


async def test_is_admin_true_for_administrator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is True
    bot.get_chat_member.assert_awaited_once_with(1, 100)


async def test_is_admin_true_for_creator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="creator")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is True


async def test_is_admin_false_for_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="member")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is False
