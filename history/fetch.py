from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Optional

import config

_TEXT_TRUNCATE_LENGTH = 120

_cache: dict[int, tuple[float, str]] = {}


@dataclass
class _HistoryItem:
    message_id: int
    kind: str
    author: str
    text: Optional[str] = None
    title: Optional[str] = None
    performer: Optional[str] = None
    duration: Optional[int] = None
    file_name: Optional[str] = None


def _clean_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) > _TEXT_TRUNCATE_LENGTH:
        return cleaned[: _TEXT_TRUNCATE_LENGTH - 1] + "…"
    return cleaned


def _author_name(message: object) -> str:
    sender = getattr(message, "sender", None)
    if sender is not None:
        name = getattr(sender, "first_name", None) or getattr(sender, "title", None)
        if name:
            return name
    return "канал"


def _extract_item(message: object) -> Optional[_HistoryItem]:
    author = _author_name(message)
    file = getattr(message, "file", None)
    if file is not None:
        title = getattr(file, "title", None)
        performer = getattr(file, "performer", None)
        duration = getattr(file, "duration", None)
        if title or performer or duration:
            return _HistoryItem(
                message_id=message.id,
                kind="audio",
                author=author,
                title=title,
                performer=performer,
                duration=duration,
            )
        file_name = getattr(file, "name", None)
        caption = _clean_text(getattr(message, "text", None))
        if not file_name and not caption:
            # Captionless media with no identifying info (e.g. a bare photo
            # with no caption) carries nothing useful to show — skip it.
            return None
        return _HistoryItem(
            message_id=message.id,
            kind="document",
            author=author,
            file_name=file_name,
            text=caption,
        )
    text = _clean_text(getattr(message, "text", None))
    if text is None:
        return None
    return _HistoryItem(message_id=message.id, kind="text", author=author, text=text)


def _message_link(chat_id: int, message_id: int) -> Optional[str]:
    if chat_id > -1_000_000_000_000:
        return None
    internal_id = -chat_id - 1_000_000_000_000
    return f"https://t.me/c/{internal_id}/{message_id}"


def _format_duration(duration: Optional[int]) -> str:
    if not duration:
        return ""
    minutes, seconds = divmod(int(duration), 60)
    return f" ({minutes}:{seconds:02d})"


def _format_item(chat_id: int, index: int, item: _HistoryItem) -> str:
    link = _message_link(chat_id, item.message_id)
    suffix = f" — {link}" if link else ""

    if item.kind == "audio":
        parts = " — ".join(p for p in (item.performer, item.title) if p) or "без названия"
        return f"{index}. [аудио] {parts}{_format_duration(item.duration)}{suffix}"
    if item.kind == "document":
        name = item.file_name or "файл без имени"
        caption = f" — {item.text}" if item.text else ""
        return f"{index}. [файл] {name}{caption}{suffix}"
    return f"{index}. {item.author}: {item.text}{suffix}"


def _render(chat_id: int, messages: list) -> str:
    items = [
        item for item in (_extract_item(message) for message in messages) if item is not None
    ]
    if not items:
        return (
            "В этом чате пока нет проиндексированной истории "
            "(нет текстовых сообщений или файлов)."
        )

    lines = [f"В этом чате доступно {len(items)} сообщений/файлов из последних {len(messages)}:"]
    lines.extend(_format_item(chat_id, index + 1, item) for index, item in enumerate(items))
    return "\n".join(lines)


async def _collect_messages(client: object, chat_id: int, limit: int) -> list:
    messages = []
    async for message in client.iter_messages(chat_id, limit=limit):
        messages.append(message)
    return messages


async def fetch_chat_history(chat_id: int, client: object) -> str:
    if client is None:
        return "История чата недоступна: userbot не настроен."

    cached = _cache.get(chat_id)
    if cached is not None and monotonic() - cached[0] < config.HISTORY_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        messages = await _collect_messages(client, chat_id, config.HISTORY_FETCH_LIMIT)
        text = _render(chat_id, messages)
    except Exception:
        return "Не удалось получить историю чата (ошибка Telegram API)."

    _cache[chat_id] = (monotonic(), text)
    return text
