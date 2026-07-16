from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from admin.permissions import is_admin
from db.repository import Repository

router = Router(name="admin")


async def _require_admin(message: Message, bot: Bot) -> bool:
    if message.from_user is None:
        return False
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("Эта команда доступна только администраторам чата.")
        return False
    return True


@router.message(Command("addword"))
async def cmd_addword(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /addword <слово>")
        return
    word = command.args.strip()
    await repository.add_trigger_word(message.chat.id, word)
    await message.answer(f"Слово «{word}» добавлено в список триггеров.")


@router.message(Command("delword"))
async def cmd_delword(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args:
        await message.answer("Использование: /delword <слово>")
        return
    word = command.args.strip()
    deleted = await repository.delete_trigger_word(message.chat.id, word)
    if deleted:
        await message.answer(f"Слово «{word}» удалено из списка триггеров.")
    else:
        await message.answer(f"Слово «{word}» не найдено в добавленных вручную.")


@router.message(Command("listwords"))
async def cmd_listwords(message: Message, repository: Repository) -> None:
    words = await repository.list_trigger_words(message.chat.id)
    if not words:
        await message.answer("Дополнительных триггер-слов для этого чата нет.")
        return
    await message.answer("Добавленные триггер-слова:\n" + "\n".join(sorted(words)))


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
        await message.answer("Использование: /setresetdays <число дней, 0 = никогда>")
        return
    days = int(command.args.strip())
    await repository.set_reset_days(message.chat.id, days)
    await message.answer(f"Период сброса счётчика нарушений установлен: {days} дн. (0 = никогда).")


@router.message(Command("setinterval"))
async def cmd_setinterval(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /setinterval <минуты, 0 = выключить>")
        return
    minutes = int(command.args.strip())
    await repository.set_broadcast_interval(message.chat.id, minutes)
    await message.answer(f"Интервал рассылки установлен: {minutes} мин. (0 = выключено).")


@router.message(Command("addmsg"))
async def cmd_addmsg(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args:
        await message.answer("Использование: /addmsg <текст сообщения>")
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
        await message.answer("Использование: /delmsg <номер из /listmsgs>")
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
    lines = [f"{msg_id}: {text}" for msg_id, text in messages]
    await message.answer("Сообщения рассылки:\n" + "\n".join(lines))
