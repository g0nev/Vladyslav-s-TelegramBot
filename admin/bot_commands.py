from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="ask", description="Задать вопрос ИИ: /ask «вопрос»"),
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
    BotCommand(command="setmuteminutes", description="Длительность мьюта в минутах (админ)"),
    BotCommand(command="setkickafter", description="Номер нарушения, после которого кик (админ, ≥2)"),
    BotCommand(command="setpersona", description="Задать характер/стиль поведения бота, без текста — сбросить (админ)"),
    BotCommand(
        command="setproactive",
        description="Проактивные сообщения: off / interval «мин» / chance «%» (админ)",
    ),
    BotCommand(
        command="setproactivecontext",
        description="Сколько последних сообщений учитывать в проактивном ответе, 1-10 (админ)",
    ),
    BotCommand(command="pin", description="Закрепить сообщение (админ, ответом на сообщение)"),
    BotCommand(command="unpin", description="Открепить сообщение (админ)"),
    BotCommand(command="lock", description="Заблокировать чат — писать могут только админы (админ)"),
    BotCommand(command="unlock", description="Разблокировать чат (админ)"),
    BotCommand(command="newlink", description="Создать новую инвайт-ссылку (админ)"),
    BotCommand(command="revokelink", description="Отозвать последнюю инвайт-ссылку (админ)"),
    BotCommand(command="chatinfo", description="Информация о чате: участники и админы"),
    BotCommand(command="settitle", description="Изменить название чата (админ)"),
    BotCommand(command="setdescription", description="Изменить описание чата (админ)"),
    BotCommand(command="setphoto", description="Изменить фото чата (админ, фото с подписью /setphoto)"),
]


async def register_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
