from __future__ import annotations

import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from admin.permissions import require_admin as _require_admin
from ai.content_filter import check_hard_block
from ai.handlers import BLOCK_MESSAGE
from db.repository import Repository
from scheduler.broadcaster import schedule_chat_broadcast
from scheduler.proactive import schedule_chat_proactive

router = Router(name="admin")


@router.message(Command("addword"))
@router.channel_post(Command("addword"))
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
@router.channel_post(Command("delword"))
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
@router.channel_post(Command("listwords"))
async def cmd_listwords(message: Message, repository: Repository) -> None:
    words = await repository.list_trigger_words(message.chat.id)
    if not words:
        await message.answer("Дополнительных триггер-слов для этого чата нет.")
        return
    escaped_words = (html.escape(word) for word in sorted(words))
    await message.answer("Добавленные триггер-слова:\n" + "\n".join(escaped_words))


@router.message(Command("warns"))
@router.channel_post(Command("warns"))
async def cmd_warns(message: Message, repository: Repository) -> None:
    if message.reply_to_message is None or message.reply_to_message.from_user is None:
        await message.answer("Ответьте этой командой на сообщение пользователя.")
        return
    target = message.reply_to_message.from_user
    count, _ = await repository.get_warning(message.chat.id, target.id)
    await message.answer(f"У пользователя {target.mention_html()} {count} предупреждений.")


@router.message(Command("resetwarns"))
@router.channel_post(Command("resetwarns"))
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
@router.channel_post(Command("setresetdays"))
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
@router.channel_post(Command("setinterval"))
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
@router.channel_post(Command("setmuteminutes"))
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
@router.channel_post(Command("setkickafter"))
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
@router.channel_post(Command("addmsg"))
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
@router.channel_post(Command("delmsg"))
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
@router.channel_post(Command("listmsgs"))
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
@router.channel_post(Command("setwarnmsg"))
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
@router.channel_post(Command("setmutemsg"))
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
@router.channel_post(Command("setkickmsg"))
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
@router.channel_post(Command("resetmsgs"))
async def cmd_resetmsgs(message: Message, bot: Bot, repository: Repository) -> None:
    if not await _require_admin(message, bot):
        return
    await repository.reset_message_templates(message.chat.id)
    await message.answer("Тексты наказаний сброшены к значениям по умолчанию.")


@router.message(Command("setpersona"))
@router.channel_post(Command("setpersona"))
async def cmd_setpersona(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    text = command.args.strip() if command.args else ""
    if not text:
        await repository.set_persona(message.chat.id, None)
        await message.answer("Инструкция поведения сброшена, бот вернулся к обычному стилю.")
        return
    if check_hard_block(text):
        await message.answer(BLOCK_MESSAGE)
        return
    if len(text) > 500:
        await message.answer("Слишком длинно — уложись в 500 символов.")
        return
    await repository.set_persona(message.chat.id, text)
    await message.answer("Инструкция поведения сохранена.")


_SETPROACTIVE_USAGE = (
    "Использование:\n"
    "/setproactive off — выключить\n"
    "/setproactive interval «минуты» — раз в N минут, если было новое сообщение\n"
    "/setproactive chance «процент 1-100» — шанс среагировать на каждое сообщение"
)


@router.message(Command("setproactive"))
@router.channel_post(Command("setproactive"))
async def cmd_setproactive(
    message: Message,
    command: CommandObject,
    bot: Bot,
    repository: Repository,
    scheduler: AsyncIOScheduler,
) -> None:
    if not await _require_admin(message, bot):
        return

    args = command.args.strip().split(maxsplit=1) if command.args else []
    if not args:
        await message.answer(_SETPROACTIVE_USAGE)
        return

    subcommand = args[0].lower()

    if subcommand == "off":
        await repository.set_proactive_off(message.chat.id)
        schedule_chat_proactive(scheduler, bot, repository, message.chat.id, 0)
        await message.answer("Проактивные сообщения выключены.")
        return

    if subcommand == "interval":
        if len(args) < 2 or not args[1].strip().isdigit() or int(args[1].strip()) <= 0:
            await message.answer(_SETPROACTIVE_USAGE)
            return
        minutes = int(args[1].strip())
        await repository.set_proactive_interval(message.chat.id, minutes)
        schedule_chat_proactive(scheduler, bot, repository, message.chat.id, minutes)
        await message.answer(
            f"Проактивный режим: раз в {minutes} мин. (если были новые сообщения)."
        )
        return

    if subcommand == "chance":
        if len(args) < 2 or not args[1].strip().isdigit():
            await message.answer(_SETPROACTIVE_USAGE)
            return
        percent = int(args[1].strip())
        if percent < 1 or percent > 100:
            await message.answer(_SETPROACTIVE_USAGE)
            return
        await repository.set_proactive_probability(message.chat.id, percent / 100.0)
        schedule_chat_proactive(scheduler, bot, repository, message.chat.id, 0)
        await message.answer(f"Проактивный режим: {percent}% шанс среагировать на сообщение.")
        return

    await message.answer(_SETPROACTIVE_USAGE)


@router.message(Command("setproactivecontext"))
@router.channel_post(Command("setproactivecontext"))
async def cmd_setproactivecontext(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /setproactivecontext «число сообщений, 1-10»")
        return
    size = int(command.args.strip())
    if size < 1 or size > 10:
        await message.answer("Использование: /setproactivecontext «число сообщений, 1-10»")
        return
    await repository.set_proactive_context_size(message.chat.id, size)
    await message.answer(f"Проактивный контекст: последние {size} сообщений.")
