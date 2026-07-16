from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import CommandObject
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from admin import commands
from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


@pytest.fixture
def scheduler():
    sched = AsyncIOScheduler()
    yield sched
    if sched.running:
        sched.shutdown(wait=False)


def make_message(user_id=1, chat_id=1, reply_to=None):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=from_user,
        reply_to_message=reply_to,
        answer=AsyncMock(),
    )


def make_reply_user(user_id):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(from_user=from_user)


async def make_bot(is_admin_user_id=1):
    bot = AsyncMock()

    async def get_chat_member(chat_id, user_id):
        status = "administrator" if user_id == is_admin_user_id else "member"
        return SimpleNamespace(status=status)

    bot.get_chat_member.side_effect = get_chat_member
    return bot


def cmd(args):
    return CommandObject(prefix="/", command="x", args=args)


async def test_addword_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd("спам"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    assert await repo.list_trigger_words(1) == []


async def test_addword_adds_word(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd("спам"), bot, repo)

    assert await repo.list_trigger_words(1) == ["спам"]


async def test_addword_without_args(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd(None), bot, repo)

    message.answer.assert_awaited_once_with("Использование: /addword <слово>")


async def test_addword_whitespace_only_args(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd("   "), bot, repo)

    message.answer.assert_awaited_once_with("Использование: /addword <слово>")
    assert await repo.list_trigger_words(1) == []


async def test_delword_removes_existing(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.add_trigger_word(1, "спам")
    message = make_message(user_id=1)

    await commands.cmd_delword(message, cmd("спам"), bot, repo)

    assert await repo.list_trigger_words(1) == []


async def test_listwords_empty(repo):
    message = make_message(user_id=1)

    await commands.cmd_listwords(message, repo)

    message.answer.assert_awaited_once_with("Дополнительных триггер-слов для этого чата нет.")


async def test_warns_reports_count(repo):
    await repo.set_warning(chat_id=1, user_id=42, count=2, last_violation_at="2026-07-15T00:00:00")
    message = make_message(user_id=1, reply_to=make_reply_user(42))

    await commands.cmd_warns(message, repo)

    message.answer.assert_awaited_once()
    assert "2" in message.answer.await_args.args[0]


async def test_resetwarns_clears_count(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_warning(chat_id=1, user_id=42, count=2, last_violation_at="2026-07-15T00:00:00")
    message = make_message(user_id=1, reply_to=make_reply_user(42))

    await commands.cmd_resetwarns(message, bot, repo)

    count, _ = await repo.get_warning(1, 42)
    assert count == 0


async def test_setresetdays_rejects_non_numeric(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setresetdays(message, cmd("много"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Использование: /setresetdays <число дней, 0 = никогда>"
    )


async def test_setresetdays_updates_value(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setresetdays(message, cmd("7"), bot, repo)

    _, reset_days = await repo.get_chat_settings(1)
    assert reset_days == 7


async def test_setinterval_updates_value(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setinterval(message, cmd("15"), bot, repo, scheduler)

    interval, _ = await repo.get_chat_settings(1)
    assert interval == 15
    assert scheduler.get_job("broadcast_1") is not None


async def test_addmsg_and_listmsgs(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addmsg(message, cmd("Привет всем!"), bot, repo)
    await commands.cmd_listmsgs(message, bot, repo)

    stored = await repo.list_broadcast_messages(1)
    assert stored[0][1] == "Привет всем!"


async def test_listmsgs_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    await repo.add_broadcast_message(1, "Секретное сообщение")
    message = make_message(user_id=1)

    await commands.cmd_listmsgs(message, bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )


async def test_delmsg_removes_message(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)
    msg_id = await repo.add_broadcast_message(1, "Текст")

    await commands.cmd_delmsg(message, cmd(str(msg_id)), bot, repo)

    assert await repo.list_broadcast_messages(1) == []


async def test_setwarnmsg_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    message = make_message(user_id=1)

    await commands.cmd_setwarnmsg(message, cmd("Текст"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    assert (await repo.get_message_templates(1))[0] is None


async def test_setwarnmsg_sets_template(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setwarnmsg(message, cmd("Осторожно, {mention}!"), bot, repo)

    templates = await repo.get_message_templates(1)
    assert templates[0] == "Осторожно, {mention}!"


async def test_setwarnmsg_without_args_shows_usage(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setwarnmsg(message, cmd(None), bot, repo)

    assert "Использование: /setwarnmsg" in message.answer.await_args.args[0]


async def test_setmutemsg_sets_template(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setmutemsg(message, cmd("{mention} молчит {minutes} мин."), bot, repo)

    templates = await repo.get_message_templates(1)
    assert templates[1] == "{mention} молчит {minutes} мин."


async def test_setkickmsg_sets_template(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setkickmsg(message, cmd("Пока, {mention}."), bot, repo)

    templates = await repo.get_message_templates(1)
    assert templates[2] == "Пока, {mention}."


async def test_resetmsgs_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    await repo.set_warn_message(1, "кастом")
    message = make_message(user_id=1)

    await commands.cmd_resetmsgs(message, bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    assert (await repo.get_message_templates(1))[0] == "кастом"


async def test_resetmsgs_clears_all_templates(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_warn_message(1, "кастом")
    await repo.set_mute_message(1, "кастом")
    await repo.set_kick_message(1, "кастом")
    message = make_message(user_id=1)

    await commands.cmd_resetmsgs(message, bot, repo)

    assert await repo.get_message_templates(1) == (None, None, None)
