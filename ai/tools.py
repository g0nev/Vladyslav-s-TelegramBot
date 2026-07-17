from __future__ import annotations

import html
from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import Repository
from scheduler.broadcaster import schedule_chat_broadcast


def _no_args() -> dict:
    return {"type": "object", "properties": {}}


def _tool(name: str, description: str, parameters: Optional[dict] = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters if parameters is not None else _no_args(),
        },
    }


PUBLIC_TOOLS: list[dict] = [
    _tool("list_trigger_words", "Показать список добавленных вручную триггер-слов чата."),
    _tool(
        "get_user_warnings",
        "Показать количество предупреждений у пользователя. "
        "Цель берётся из сообщения, на которое ответили; аргументов нет.",
    ),
    _tool("list_broadcast_messages", "Показать пул сообщений автоматической рассылки."),
]

ADMIN_ONLY_TOOLS: list[dict] = [
    _tool(
        "add_trigger_word",
        "Добавить слово в список триггеров модерации.",
        {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "Слово-триггер."}},
            "required": ["word"],
        },
    ),
    _tool(
        "delete_trigger_word",
        "Удалить слово из добавленных вручную триггеров.",
        {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "Слово-триггер."}},
            "required": ["word"],
        },
    ),
    _tool(
        "reset_user_warnings",
        "Сбросить счётчик предупреждений пользователя. "
        "Цель берётся из сообщения, на которое ответили; аргументов нет.",
    ),
    _tool(
        "mute_user",
        "Ограничить пользователю отправку сообщений на указанное число минут. "
        "Цель берётся из сообщения, на которое ответили.",
        {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Длительность мьюта в минутах."}
            },
            "required": ["minutes"],
        },
    ),
    _tool(
        "kick_user",
        "Удалить пользователя из чата (с возможностью вернуться по ссылке). "
        "Цель берётся из сообщения, на которое ответили; аргументов нет.",
    ),
    _tool(
        "set_reset_days",
        "Установить период автосброса счётчика нарушений в днях (0 = никогда).",
        {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Число дней, 0 = никогда."}},
            "required": ["days"],
        },
    ),
    _tool(
        "set_broadcast_interval",
        "Установить интервал автоматической рассылки в минутах (0 = выключить).",
        {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Интервал в минутах, 0 = выключить."}
            },
            "required": ["minutes"],
        },
    ),
    _tool(
        "add_broadcast_message",
        "Добавить текст в пул сообщений автоматической рассылки.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст сообщения."}},
            "required": ["text"],
        },
    ),
    _tool(
        "delete_broadcast_message",
        "Удалить сообщение из пула рассылки по его номеру.",
        {
            "type": "object",
            "properties": {
                "message_id": {"type": "integer", "description": "Номер сообщения из списка."}
            },
            "required": ["message_id"],
        },
    ),
    _tool(
        "set_warn_message",
        "Задать текст предупреждения за 1-е нарушение. Плейсхолдеры: {mention}, {minutes}.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст предупреждения."}},
            "required": ["text"],
        },
    ),
    _tool(
        "set_mute_message",
        "Задать текст мьюта за 2-е нарушение. Плейсхолдеры: {mention}, {minutes}.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст мьюта."}},
            "required": ["text"],
        },
    ),
    _tool(
        "set_kick_message",
        "Задать текст кика за 3-е нарушение. Плейсхолдеры: {mention}, {minutes}.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст кика."}},
            "required": ["text"],
        },
    ),
    _tool(
        "reset_punishment_messages",
        "Сбросить тексты наказаний (предупреждение/мьют/кик) к значениям по умолчанию.",
    ),
]

ADMIN_TOOLS: list[dict] = PUBLIC_TOOLS + ADMIN_ONLY_TOOLS

PUBLIC_TOOL_NAMES: set[str] = {schema["function"]["name"] for schema in PUBLIC_TOOLS}
ADMIN_TOOL_NAMES: set[str] = {schema["function"]["name"] for schema in ADMIN_TOOLS}

TARGET_REQUIRED_TOOLS: set[str] = {
    "get_user_warnings",
    "reset_user_warnings",
    "mute_user",
    "kick_user",
}
CONFIRMATION_TOOLS: set[str] = {"mute_user", "kick_user"}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def execute_tool(
    tool_name: str,
    arguments: dict,
    *,
    bot: Bot,
    repository: Repository,
    scheduler: AsyncIOScheduler,
    chat_id: int,
    target_id: Optional[int] = None,
    target_mention: Optional[str] = None,
) -> str:
    if tool_name == "list_trigger_words":
        words = await repository.list_trigger_words(chat_id)
        if not words:
            return "Дополнительных триггер-слов нет."
        escaped_words = (html.escape(word) for word in sorted(words))
        return "Триггер-слова:\n" + "\n".join(escaped_words)

    if tool_name == "get_user_warnings":
        count, _ = await repository.get_warning(chat_id, target_id)
        return f"У {target_mention} {count} предупреждений."

    if tool_name == "list_broadcast_messages":
        messages = await repository.list_broadcast_messages(chat_id)
        if not messages:
            return "Пул сообщений рассылки пуст."
        lines = [f"{msg_id}: {html.escape(text)}" for msg_id, text in messages]
        return "Сообщения рассылки:\n" + "\n".join(lines)

    if tool_name == "add_trigger_word":
        word = str(arguments.get("word", "")).strip()
        if not word:
            return "Нужно указать непустое слово."
        await repository.add_trigger_word(chat_id, word)
        return f"Слово «{html.escape(word)}» добавлено в список триггеров."

    if tool_name == "delete_trigger_word":
        word = str(arguments.get("word", "")).strip()
        if not word:
            return "Нужно указать непустое слово."
        deleted = await repository.delete_trigger_word(chat_id, word)
        if deleted:
            return f"Слово «{html.escape(word)}» удалено из списка триггеров."
        return f"Слово «{html.escape(word)}» не найдено в добавленных вручную."

    if tool_name == "reset_user_warnings":
        await repository.reset_warning(chat_id, target_id)
        return f"Счётчик нарушений {target_mention} сброшен."

    if tool_name == "set_reset_days":
        days = _as_int(arguments.get("days"))
        await repository.set_reset_days(chat_id, days)
        return f"Период сброса счётчика нарушений: {days} дн. (0 = никогда)."

    if tool_name == "set_broadcast_interval":
        minutes = _as_int(arguments.get("minutes"))
        await repository.set_broadcast_interval(chat_id, minutes)
        schedule_chat_broadcast(scheduler, bot, repository, chat_id, minutes)
        return f"Интервал рассылки: {minutes} мин. (0 = выключено)."

    if tool_name == "add_broadcast_message":
        text = str(arguments.get("text", "")).strip()
        if not text:
            return "Нужно указать непустой текст сообщения."
        await repository.add_broadcast_message(chat_id, text)
        return "Сообщение добавлено в пул рассылки."

    if tool_name == "delete_broadcast_message":
        message_id = _as_int(arguments.get("message_id"))
        deleted = await repository.delete_broadcast_message(chat_id, message_id)
        if deleted:
            return "Сообщение удалено из пула рассылки."
        return "Сообщение с таким номером не найдено."

    if tool_name == "set_warn_message":
        text = str(arguments.get("text", "")).strip()
        if not text:
            return "Нужно указать непустой текст."
        await repository.set_warn_message(chat_id, text)
        return "Текст предупреждения (1-е нарушение) обновлён."

    if tool_name == "set_mute_message":
        text = str(arguments.get("text", "")).strip()
        if not text:
            return "Нужно указать непустой текст."
        await repository.set_mute_message(chat_id, text)
        return "Текст мьюта (2-е нарушение) обновлён."

    if tool_name == "set_kick_message":
        text = str(arguments.get("text", "")).strip()
        if not text:
            return "Нужно указать непустой текст."
        await repository.set_kick_message(chat_id, text)
        return "Текст кика (3-е нарушение) обновлён."

    if tool_name == "reset_punishment_messages":
        await repository.reset_message_templates(chat_id)
        return "Тексты наказаний сброшены к значениям по умолчанию."

    return "Не могу выполнить этот запрос."
