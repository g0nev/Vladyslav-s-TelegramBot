from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Optional

_BUFFER_CAP = 20
MIN_COOLDOWN_SECONDS = 60.0


@dataclass
class _BufferedMessage:
    author: str
    text: str
    message_id: int


_buffers: dict[int, deque[_BufferedMessage]] = {}
_last_fired_message_id: dict[int, int] = {}
_last_fired_at: dict[int, float] = {}


def record_message(chat_id: int, author: str, text: str, message_id: int) -> None:
    chat_buffer = _buffers.setdefault(chat_id, deque(maxlen=_BUFFER_CAP))
    chat_buffer.append(_BufferedMessage(author=author, text=text, message_id=message_id))


def get_recent(chat_id: int, n: int) -> list[str]:
    chat_buffer = _buffers.get(chat_id)
    if not chat_buffer:
        return []
    return [f"{msg.author}: {msg.text}" for msg in list(chat_buffer)[-n:]]


def latest_message_id(chat_id: int) -> Optional[int]:
    chat_buffer = _buffers.get(chat_id)
    if not chat_buffer:
        return None
    return chat_buffer[-1].message_id


def has_new_since_last_fire(chat_id: int) -> bool:
    latest = latest_message_id(chat_id)
    if latest is None:
        return False
    return latest != _last_fired_message_id.get(chat_id)


def mark_fired(chat_id: int, message_id: int) -> None:
    _last_fired_message_id[chat_id] = message_id
    _last_fired_at[chat_id] = monotonic()


def cooldown_elapsed(chat_id: int) -> bool:
    last_fired_at = _last_fired_at.get(chat_id)
    if last_fired_at is None:
        return True
    return (monotonic() - last_fired_at) >= MIN_COOLDOWN_SECONDS
