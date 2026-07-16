from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import Repository
from scheduler.broadcaster import (
    load_scheduled_broadcasts,
    schedule_chat_broadcast,
    send_broadcast,
)


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


async def test_send_broadcast_picks_message(repo):
    bot = AsyncMock()
    await repo.add_broadcast_message(chat_id=1, text="Привет!")

    await send_broadcast(bot, repo, chat_id=1)

    bot.send_message.assert_awaited_once_with(1, "Привет!")


async def test_send_broadcast_skips_when_pool_empty(repo):
    bot = AsyncMock()

    await send_broadcast(bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_schedule_chat_broadcast_registers_job(repo, scheduler):
    bot = AsyncMock()

    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    assert scheduler.get_job("broadcast_1") is not None


async def test_schedule_chat_broadcast_removes_job_when_zero(repo, scheduler):
    bot = AsyncMock()
    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=0)

    assert scheduler.get_job("broadcast_1") is None


async def test_load_scheduled_broadcasts_registers_active_chats(repo, scheduler):
    bot = AsyncMock()
    await repo.set_broadcast_interval(chat_id=1, minutes=45)
    await repo.set_broadcast_interval(chat_id=2, minutes=0)

    await load_scheduled_broadcasts(scheduler, bot, repo)

    assert scheduler.get_job("broadcast_1") is not None
    assert scheduler.get_job("broadcast_2") is None


async def test_scheduled_broadcast_job_removes_job_on_api_error(repo, scheduler):
    from aiogram.exceptions import TelegramAPIError

    from scheduler.broadcaster import _scheduled_broadcast_job

    bot = AsyncMock()
    bot.send_message.side_effect = TelegramAPIError(method=None, message="bot was kicked")
    await repo.add_broadcast_message(chat_id=1, text="Привет!")
    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    await _scheduled_broadcast_job(scheduler, bot, repo, chat_id=1)

    assert scheduler.get_job("broadcast_1") is None
