from types import SimpleNamespace
from unittest.mock import AsyncMock

from admin.permissions import is_admin, require_admin


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


def _make_message(user_id, chat_type="group"):
    from_user = None if user_id is None else SimpleNamespace(id=user_id)
    return SimpleNamespace(
        chat=SimpleNamespace(id=1, type=chat_type), from_user=from_user, answer=AsyncMock()
    )


async def test_require_admin_true_for_admin():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
    message = _make_message(user_id=100)

    assert await require_admin(message, bot) is True
    message.answer.assert_not_called()


async def test_require_admin_false_and_notifies_for_non_admin():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="member")
    message = _make_message(user_id=100)

    assert await require_admin(message, bot) is False
    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )


async def test_require_admin_false_for_anonymous_user():
    bot = AsyncMock()
    message = _make_message(user_id=None)

    assert await require_admin(message, bot) is False
    bot.get_chat_member.assert_not_called()


async def test_require_admin_true_for_channel_post_without_user():
    bot = AsyncMock()
    message = _make_message(user_id=None, chat_type="channel")

    assert await require_admin(message, bot) is True
    bot.get_chat_member.assert_not_called()
    message.answer.assert_not_called()
