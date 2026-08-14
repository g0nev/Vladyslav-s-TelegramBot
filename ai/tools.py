from __future__ import annotations

import html
import re
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
    _tool(
        "list_broadcast_messages",
        "Показать пул текстов автоматической рассылки от лица бота (это не файлы и не "
        "сообщения самого чата — для содержимого чата есть read_chat_history).",
    ),
]

ADMIN_ONLY_TOOLS: list[dict] = [
    _tool(
        "add_trigger_word",
        "Добавить одно или несколько слов в список триггеров модерации. Каждое слово — "
        "отдельный элемент массива words; указывай только настоящие слова, никаких "
        "шаблонных плейсхолдеров вида «слово_1», «слово_2».",
        {
            "type": "object",
            "properties": {
                "words": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Список реальных слов-триггеров, каждое отдельным элементом.",
                }
            },
            "required": ["words"],
        },
    ),
    _tool(
        "delete_trigger_word",
        "Удалить одно или несколько слов из добавленных вручную триггеров. Каждое "
        "слово — отдельный элемент массива words.",
        {
            "type": "object",
            "properties": {
                "words": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Список слов-триггеров на удаление, каждое отдельным элементом.",
                }
            },
            "required": ["words"],
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
        "Добавить текст в пул автоматической рассылки бота (не связано с файлами/"
        "сообщениями чата).",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Текст сообщения."}},
            "required": ["text"],
        },
    ),
    _tool(
        "delete_broadcast_message",
        "Удалить текст из пула автоматической рассылки бота по его номеру (не связано с "
        "файлами/сообщениями чата).",
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
    _tool(
        "set_mute_minutes",
        "Установить длительность мьюта в минутах для этого чата.",
        {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Длительность мьюта в минутах."}
            },
            "required": ["minutes"],
        },
    ),
    _tool(
        "set_kick_after",
        "Установить, после какого по счёту нарушения происходит кик (минимум 2).",
        {
            "type": "object",
            "properties": {
                "violations": {
                    "type": "integer",
                    "description": "Номер нарушения, после которого кик, минимум 2.",
                }
            },
            "required": ["violations"],
        },
    ),
    _tool(
        "set_max_tokens",
        "Установить лимит длины ответа модели (в токенах) для этого чата, 50-3000.",
        {
            "type": "object",
            "properties": {
                "tokens": {
                    "type": "integer",
                    "description": "Лимит токенов ответа, число от 50 до 3000.",
                }
            },
            "required": ["tokens"],
        },
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


_PLACEHOLDER_SUFFIX = re.compile(r"_\d+$")


def _looks_like_placeholder(word: str) -> bool:
    return bool(_PLACEHOLDER_SUFFIX.search(word))


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
        raw_words = arguments.get("words")
        if not isinstance(raw_words, list):
            raw_words = [raw_words] if raw_words is not None else []
        words = [str(w).strip() for w in raw_words if str(w).strip()]
        if not words:
            return "Нужно указать хотя бы одно непустое слово."

        crammed = [w for w in words if "," in w or "\n" in w]
        if crammed:
            return (
                "Каждое слово нужно передавать отдельным элементом списка words, "
                "без запятых и переносов строк внутри одного слова."
            )

        placeholders = [w for w in words if _looks_like_placeholder(w)]
        if placeholders:
            escaped_placeholders = ", ".join(f"«{html.escape(w)}»" for w in placeholders)
            return (
                "Это похоже на шаблонные плейсхолдеры, а не реальные слова: "
                f"{escaped_placeholders}. Укажи настоящие слова-триггеры."
            )

        for word in words:
            await repository.add_trigger_word(chat_id, word)

        escaped_words = ", ".join(f"«{html.escape(w)}»" for w in words)
        if len(words) == 1:
            return f"Слово {escaped_words} добавлено в список триггеров."
        return f"Слова {escaped_words} добавлены в список триггеров."

    if tool_name == "delete_trigger_word":
        raw_words = arguments.get("words")
        if not isinstance(raw_words, list):
            raw_words = [raw_words] if raw_words is not None else []
        words = [str(w).strip() for w in raw_words if str(w).strip()]
        if not words:
            return "Нужно указать хотя бы одно непустое слово."

        crammed = [w for w in words if "," in w or "\n" in w]
        if crammed:
            return (
                "Каждое слово нужно передавать отдельным элементом списка words, "
                "без запятых и переносов строк внутри одного слова."
            )

        deleted_words = []
        missing_words = []
        for word in words:
            if await repository.delete_trigger_word(chat_id, word):
                deleted_words.append(word)
            else:
                missing_words.append(word)

        parts = []
        if deleted_words:
            escaped = ", ".join(f"«{html.escape(w)}»" for w in deleted_words)
            noun = "Слово" if len(deleted_words) == 1 else "Слова"
            verb = "удалено" if len(deleted_words) == 1 else "удалены"
            parts.append(f"{noun} {escaped} {verb} из списка триггеров.")
        if missing_words:
            escaped = ", ".join(f"«{html.escape(w)}»" for w in missing_words)
            noun = "Слово" if len(missing_words) == 1 else "Слова"
            verb = "не найдено" if len(missing_words) == 1 else "не найдены"
            parts.append(f"{noun} {escaped} {verb} в добавленных вручную.")
        return " ".join(parts)

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

    if tool_name == "set_mute_minutes":
        minutes = _as_int(arguments.get("minutes"))
        if minutes <= 0:
            return "Нужно указать положительное число минут."
        await repository.set_mute_minutes(chat_id, minutes)
        return f"Длительность мьюта установлена: {minutes} мин."

    if tool_name == "set_kick_after":
        violations = _as_int(arguments.get("violations"))
        if violations < 2:
            return "Кик может происходить не раньше 2-го нарушения."
        await repository.set_kick_after(chat_id, violations)
        return f"Кик теперь происходит начиная с {violations}-го нарушения."

    if tool_name == "set_max_tokens":
        tokens = _as_int(arguments.get("tokens"))
        if tokens < 50 or tokens > 3000:
            return "Лимит токенов должен быть в диапазоне 50-3000."
        await repository.set_max_tokens(chat_id, tokens)
        return f"Лимит токенов ответа установлен: {tokens}."

    return "Не могу выполнить этот запрос."
