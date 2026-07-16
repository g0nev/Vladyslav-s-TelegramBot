import pytest

from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


async def test_chat_settings_defaults(repo):
    interval, reset_days = await repo.get_chat_settings(chat_id=1)
    assert interval == 0
    assert reset_days == 30


async def test_set_broadcast_interval(repo):
    await repo.set_broadcast_interval(chat_id=1, minutes=60)
    interval, _ = await repo.get_chat_settings(chat_id=1)
    assert interval == 60


async def test_set_reset_days(repo):
    await repo.set_reset_days(chat_id=1, days=7)
    _, reset_days = await repo.get_chat_settings(chat_id=1)
    assert reset_days == 7


async def test_trigger_words_add_list_delete(repo):
    await repo.add_trigger_word(chat_id=1, word="Спам")
    words = await repo.list_trigger_words(chat_id=1)
    assert words == ["спам"]

    deleted = await repo.delete_trigger_word(chat_id=1, word="спам")
    assert deleted is True
    assert await repo.list_trigger_words(chat_id=1) == []


async def test_delete_trigger_word_not_found(repo):
    deleted = await repo.delete_trigger_word(chat_id=1, word="нетслова")
    assert deleted is False


async def test_warning_lifecycle(repo):
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert (count, last_at) == (0, None)

    await repo.set_warning(chat_id=1, user_id=100, count=2, last_violation_at="2026-07-15T00:00:00")
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2
    assert last_at == "2026-07-15T00:00:00"

    await repo.reset_warning(chat_id=1, user_id=100)
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert (count, last_at) == (0, None)


async def test_broadcast_messages(repo):
    msg_id = await repo.add_broadcast_message(chat_id=1, text="Hello")
    assert await repo.list_broadcast_messages(chat_id=1) == [(msg_id, "Hello")]

    deleted = await repo.delete_broadcast_message(chat_id=1, message_id=msg_id)
    assert deleted is True
    assert await repo.list_broadcast_messages(chat_id=1) == []


async def test_list_active_broadcast_chats(repo):
    await repo.set_broadcast_interval(chat_id=1, minutes=30)
    await repo.set_broadcast_interval(chat_id=2, minutes=0)
    active = await repo.list_active_broadcast_chats()
    assert active == [(1, 30)]
