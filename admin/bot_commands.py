from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="addword", description="Добавить слово-триггер (админ)"),
    BotCommand(command="delword", description="Удалить слово-триггер (админ)"),
    BotCommand(command="listwords", description="Показать добавленные триггер-слова"),
    BotCommand(command="warns", description="Показать счётчик нарушений (ответом на сообщение)"),
    BotCommand(command="resetwarns", description="Сбросить счётчик нарушений (админ, ответом на сообщение)"),
    BotCommand(command="setresetdays", description="Период автосброса счётчика в днях (админ)"),
    BotCommand(command="setinterval", description="Интервал рассылки в минутах, 0 = выключить (админ)"),
    BotCommand(command="addmsg", description="Добавить сообщение в пул рассылки (админ)"),
    BotCommand(command="delmsg", description="Удалить сообщение из пула рассылки (админ)"),
    BotCommand(command="listmsgs", description="Показать пул сообщений рассылки (админ)"),
    BotCommand(command="setwarnmsg", description="Текст предупреждения за 1-е нарушение (админ)"),
    BotCommand(command="setmutemsg", description="Текст мьюта за 2-е нарушение (админ)"),
    BotCommand(command="setkickmsg", description="Текст кика за 3-е нарушение (админ)"),
    BotCommand(command="resetmsgs", description="Сбросить тексты наказаний к стандартным (админ)"),
]


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
