from __future__ import annotations

import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from admin.permissions import require_admin as _require_admin
from db.repository import Repository
from scheduler.broadcaster import schedule_chat_broadcast

router = Router(name="admin")


@router.message(Command("addword"))
async def cmd_addword(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /addword «слово»")
        return
    word = command.args.strip()
    await repository.add_trigger_word(message.chat.id, word)
    await message.answer(f"Слово «{html.escape(word)}» добавлено в список триггеров.")


@router.message(Command("delword"))
async def cmd_delword(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args:
        await message.answer("Использование: /delword «слово»")
        return
    word = command.args.strip()
    deleted = await repository.delete_trigger_word(message.chat.id, word)
    if deleted:
        await message.answer(f"Слово «{html.escape(word)}» удалено из списка триггеров.")
    else:
        await message.answer(f"Слово «{html.escape(word)}» не найдено в добавленных вручную.")


@router.message(Command("listwords"))
async def cmd_listwords(message: Message, repository: Repository) -> None:
    words = await repository.list_trigger_words(message.chat.id)
    if not words:
        await message.answer("Дополнительных триггер-слов для этого чата нет.")
        return
    escaped_words = (html.escape(word) for word in sorted(words))
    await message.answer("Добавленные триггер-слова:\n" + "\n".join(escaped_words))


@router.message(Command("warns"))
async def cmd_warns(message: Message, repository: Repository) -> None:
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer("Ответьте этой командой на сообщение пользователя.")
        return
    target = message.reply_to_message.from_user
    count, _ = await repository.get_warning(message.chat.id, target.id)
    await message.answer(f"У пользователя {target.mention_html()} {count} предупреждений.")


@router.message(Command("resetwarns"))
async def cmd_resetwarns(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer("Ответьте этой командой на сообщение пользователя.")
        return
    target = message.reply_to_message.from_user
    await repository.reset_warning(message.chat.id, target.id)
    await message.answer(f"Счётчик нарушений пользователя {target.mention_html()} сброшен.")


@router.message(Command("setresetdays"))
async def cmd_setresetdays(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /setresetdays «число дней, 0 = никогда»")
        return
    days = int(command.args.strip())
    await repository.set_reset_days(message.chat.id, days)
    await message.answer(f"Период сброса счётчика нарушений установлен: {days} дн. (0 = никогда).")


@router.message(Command("setinterval"))
async def cmd_setinterval(
    message: Message,
    command: CommandObject,
    bot: Bot,
    repository: Repository,
    scheduler: AsyncIOScheduler,
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /setinterval «минуты, 0 = выключить»")
        return
    minutes = int(command.args.strip())
    await repository.set_broadcast_interval(message.chat.id, minutes)
    schedule_chat_broadcast(scheduler, bot, repository, message.chat.id, minutes)
    await message.answer(f"Интервал рассылки установлен: {minutes} мин. (0 = выключено).")


@router.message(Command("setmuteminutes"))
async def cmd_setmuteminutes(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if (
        not command.args
        or not command.args.strip().isdigit()
        or int(command.args.strip()) <= 0
    ):
        await message.answer("Использование: /setmuteminutes «число минут, больше 0»")
        return
    minutes = int(command.args.strip())
    await repository.set_mute_minutes(message.chat.id, minutes)
    await message.answer(f"Длительность мьюта установлена: {minutes} мин.")


@router.message(Command("setkickafter"))
async def cmd_setkickafter(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit() or int(command.args.strip()) < 2:
        await message.answer("Использование: /setkickafter «число ≥ 2»")
        return
    violations = int(command.args.strip())
    await repository.set_kick_after(message.chat.id, violations)
    await message.answer(f"Кик теперь происходит начиная с {violations}-го нарушения.")


@router.message(Command("addmsg"))
async def cmd_addmsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args:
        await message.answer("Использование: /addmsg «текст сообщения»")
        return
    await repository.add_broadcast_message(message.chat.id, command.args)
    await message.answer("Сообщение добавлено в пул рассылки.")


@router.message(Command("delmsg"))
async def cmd_delmsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /delmsg «номер из /listmsgs»")
        return
    message_id = int(command.args.strip())
    deleted = await repository.delete_broadcast_message(message.chat.id, message_id)
    if deleted:
        await message.answer("Сообщение удалено из пула рассылки.")
    else:
        await message.answer("Сообщение с таким номером не найдено.")


@router.message(Command("listmsgs"))
async def cmd_listmsgs(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    messages = await repository.list_broadcast_messages(message.chat.id)
    if not messages:
        await message.answer("Пул сообщений рассылки пуст.")
        return
    lines = [f"{msg_id}: {html.escape(text)}" for msg_id, text in messages]
    await message.answer("Сообщения рассылки:\n" + "\n".join(lines))


_SETMSG_USAGE = (
    "Использование: {command} «текст»\n"
    "Доступные плейсхолдеры: {{mention}} — упоминание пользователя, "
    "{{minutes}} — длительность мьюта в минутах."
)


@router.message(Command("setwarnmsg"))
async def cmd_setwarnmsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer(_SETMSG_USAGE.format(command="/setwarnmsg"))
        return
    await repository.set_warn_message(message.chat.id, command.args)
    await message.answer("Текст предупреждения (1-е нарушение) обновлён.")


@router.message(Command("setmutemsg"))
async def cmd_setmutemsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer(_SETMSG_USAGE.format(command="/setmutemsg"))
        return
    await repository.set_mute_message(message.chat.id, command.args)
    await message.answer("Текст мьюта (2-е нарушение) обновлён.")


@router.message(Command("setkickmsg"))
async def cmd_setkickmsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer(_SETMSG_USAGE.format(command="/setkickmsg"))
        return
    await repository.set_kick_message(message.chat.id, command.args)
    await message.answer("Текст кика (3-е нарушение) обновлён.")


@router.message(Command("resetmsgs"))
async def cmd_resetmsgs(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    await repository.reset_message_templates(message.chat.id)
    await message.answer("Тексты наказаний сброшены к значениям по умолчанию.")
