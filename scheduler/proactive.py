from __future__ import annotations

import html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai.content_filter import check_hard_block
from ai.openrouter_client import generate_proactive_message
from db.repository import Repository
from proactive import buffer


def _job_id(chat_id: int) -> str:
    return f"proactive_{chat_id}"


async def _scheduled_proactive_job(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository, chat_id: int
) -> None:
    persona = await repository.get_persona(chat_id)
    if not persona:
        return
    if not buffer.has_new_since_last_fire(chat_id):
        return
    if not buffer.try_acquire_cooldown(chat_id):
        return

    _, _, _, context_size = await repository.get_proactive_settings(chat_id)
    recent = [
        line
        for line in buffer.get_recent(chat_id, context_size)
        if not check_hard_block(line)
    ]
    text = await generate_proactive_message(persona, recent)
    if not text:
        return

    try:
        await bot.send_message(chat_id, html.escape(text))
    except TelegramAPIError:
        job_id = _job_id(chat_id)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        return

    latest_id = buffer.latest_message_id(chat_id)
    if latest_id is not None:
        buffer.mark_fired(chat_id, latest_id)


def schedule_chat_proactive(
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
        _scheduled_proactive_job,
        "interval",
        minutes=interval_minutes,
        id=job_id,
        args=[scheduler, bot, repository, chat_id],
        replace_existing=True,
    )


async def load_scheduled_proactive(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository
) -> None:
    for chat_id, interval_minutes in await repository.list_active_proactive_interval_chats():
        schedule_chat_proactive(scheduler, bot, repository, chat_id, interval_minutes)
