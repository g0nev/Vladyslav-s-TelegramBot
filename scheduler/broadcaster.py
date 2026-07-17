from __future__ import annotations

import html
import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import Repository


def _job_id(chat_id: int) -> str:
    return f"broadcast_{chat_id}"


async def send_broadcast(bot: Bot, repository: Repository, chat_id: int) -> None:
    messages = await repository.list_broadcast_messages(chat_id)
    if not messages:
        return
    _, text = random.choice(messages)
    await bot.send_message(chat_id, html.escape(text))


async def _scheduled_broadcast_job(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository, chat_id: int
) -> None:
    try:
        await send_broadcast(bot, repository, chat_id)
    except TelegramAPIError:
        job_id = _job_id(chat_id)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)


def schedule_chat_broadcast(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    repository: Repository,
    chat_id: int,
    interval_minutes: int,
) -> None:
    job_id = _job_id(chat_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if interval_minutes <= 0:
        return
    scheduler.add_job(
        _scheduled_broadcast_job,
        "interval",
        minutes=interval_minutes,
        id=job_id,
        args=[scheduler, bot, repository, chat_id],
        replace_existing=True,
    )


async def load_scheduled_broadcasts(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository
) -> None:
    for chat_id, interval_minutes in await repository.list_active_broadcast_chats():
        schedule_chat_broadcast(scheduler, bot, repository, chat_id, interval_minutes)
