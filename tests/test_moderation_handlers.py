from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


async def test_custom_warn_message_is_used_when_set(repo):
    bot = await make_bot()
    await repo.set_warn_message(chat_id=1, text="Хватит спамить, {mention}!")
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once_with("Хватит спамить, User100!")


async def test_custom_warn_message_escapes_html_but_keeps_mention(repo):
    bot = await make_bot()
    await repo.set_warn_message(chat_id=1, text="<b>Стоп</b>, {mention}!")
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once_with("&lt;b&gt;Стоп&lt;/b&gt;, User100!")


async def test_default_warn_message_used_when_not_set(repo):
    bot = await make_bot()
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    sent_text = message.answer.await_args.args[0]
    assert sent_text.startswith("User100, предупреждение")


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


async def test_configured_mute_minutes_used_for_restriction_and_message(repo):
    from datetime import datetime, timedelta

    await repo.set_mute_minutes(chat_id=1, minutes=20)
    bot = await make_bot()
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    _, kwargs = bot.restrict_chat_member.await_args
    until_date = kwargs["until_date"]
    now = datetime.now(until_date.tzinfo)
    assert abs((until_date - now) - timedelta(minutes=20)) < timedelta(seconds=5)
    sent_text = message.answer.await_args.args[0]
    assert "20 минут" in sent_text


async def test_configured_kick_after_triggers_kick_earlier(repo):
    await repo.set_kick_after(chat_id=1, violations=2)
    bot = await make_bot()
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    bot.restrict_chat_member.assert_not_called()
    bot.ban_chat_member.assert_awaited_once()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 0


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


async def test_reaction_uses_ai_when_persona_set(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value="Так, полегче там!"),
    ) as mock_generate:
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    mock_generate.assert_awaited_once_with("Дерзкий стиль", "warn", 5)
    message.answer.assert_awaited_once_with("User100, Так, полегче там!")


async def test_reaction_falls_back_to_template_when_ai_returns_none(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value=None),
    ):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    sent_text = message.answer.await_args.args[0]
    assert sent_text.startswith("User100, предупреждение")


async def test_reaction_escapes_html_from_ai_response(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value="<b>совсем оборзел</b>"),
    ):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once_with("User100, &lt;b&gt;совсем оборзел&lt;/b&gt;")


async def test_ai_not_called_when_no_persona_set(repo):
    bot = await make_bot()
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction", AsyncMock()
    ) as mock_generate:
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    mock_generate.assert_not_called()
    sent_text = message.answer.await_args.args[0]
    assert sent_text.startswith("User100, предупреждение")
