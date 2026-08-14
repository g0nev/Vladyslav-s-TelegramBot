import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from admin.bot_commands import register_commands
from admin.commands import router as admin_router
from admin.group_commands import router as group_router
from ai.handlers import router as ai_router
from db.repository import Repository
from history.telethon_client import start_client
from moderation.handlers import router as moderation_router
from moderation.logic import load_trigger_words_from_file
from scheduler.broadcaster import load_scheduled_broadcasts
from scheduler.proactive import load_scheduled_proactive

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(group_router)
    dp.include_router(ai_router)
    dp.include_router(moderation_router)
    await register_commands(bot)

    repository = await Repository.create(config.DB_PATH)
    default_trigger_words = load_trigger_words_from_file(config.TRIGGER_WORDS_FILE)
    scheduler = AsyncIOScheduler()
    await load_scheduled_broadcasts(scheduler, bot, repository)
    await load_scheduled_proactive(scheduler, bot, repository)
    scheduler.start()

    telethon_client = await start_client()

    try:
        await dp.start_polling(
            bot,
            repository=repository,
            default_trigger_words=default_trigger_words,
            scheduler=scheduler,
            telethon_client=telethon_client,
        )
    finally:
        scheduler.shutdown(wait=False)
        await repository.close()
        await bot.session.close()
        if telethon_client is not None:
            await telethon_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
