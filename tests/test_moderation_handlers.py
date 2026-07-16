from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError

from db.repository import Repository
from moderation.handlers import handle_moderated_message


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


def make_message(text, user_id=100, chat_id=1):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(
        text=text,
        from_user=from_user,
        chat=SimpleNamespace(id=chat_id),
        answer=AsyncMock(),
    )


async def make_bot(admin_ids=()):
    bot = AsyncMock()

    async def get_chat_member(chat_id, user_id):
        status = "administrator" if user_id in admin_ids else "member"
        return SimpleNamespace(status=status)

    bot.get_chat_member.side_effect = get_chat_member
    return bot


async def test_admin_messages_are_ignored(repo):
    bot = await make_bot(admin_ids={100})
    message = make_message("это спам сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_not_called()
    bot.restrict_chat_member.assert_not_called()


async def test_non_trigger_message_ignored(repo):
    bot = await make_bot()
    message = make_message("обычное сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_not_called()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 0


async def test_first_violation_sends_warning(repo):
    bot = await make_bot()
    message = make_message("это спам сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once()
    bot.restrict_chat_member.assert_not_called()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 1


async def test_second_violation_mutes(repo):
    bot = await make_bot()
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    bot.restrict_chat_member.assert_awaited_once()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2


async def test_third_violation_kicks_and_resets(repo):
    bot = await make_bot()
    message = make_message("спам")

    for _ in range(3):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    bot.ban_chat_member.assert_awaited_once()
    bot.unban_chat_member.assert_awaited_once()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 0


@pytest.fixture(autouse=True)
def clear_permission_notice_cache():
    import moderation.handlers as handlers_module

    handlers_module._last_permission_notice.clear()
    yield
    handlers_module._last_permission_notice.clear()


async def test_missing_bot_permissions_notifies_once_and_throttles(repo):
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    await repo.set_warning(chat_id=1, user_id=100, count=1, last_violation_at=now_iso)
    await repo.set_warning(chat_id=1, user_id=200, count=1, last_violation_at=now_iso)

    bot = await make_bot()
    bot.restrict_chat_member.side_effect = TelegramAPIError(method=None, message="Not enough rights")

    message1 = make_message("спам", user_id=100)
    message2 = make_message("спам", user_id=200)

    await handle_moderated_message(message1, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message2, bot, repo, default_trigger_words=["спам"])

    assert message1.answer.await_count == 1
    assert "прав администратора" in message1.answer.await_args.args[0]
    assert message2.answer.await_count == 0


async def test_missing_permissions_on_mute_does_not_bump_count(repo):
    bot = await make_bot()
    message = make_message("спам")

    # First violation succeeds normally -> count becomes 1.
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 1

    # Second violation would mute, but the bot lacks permissions.
    bot.restrict_chat_member.side_effect = TelegramAPIError(
        method=None, message="Not enough rights"
    )
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 1


async def test_missing_permissions_on_kick_does_not_reset_count(repo):
    bot = await make_bot()
    message = make_message("спам")

    # First two violations succeed normally -> count becomes 2 (mute applied).
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2

    # Third violation would kick, but the bot lacks permissions.
    bot.ban_chat_member.side_effect = TelegramAPIError(
        method=None, message="Not enough rights"
    )
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2
