from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def load_trigger_words_from_file(path: str) -> list[str]:
    words = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            words.append(stripped.lower())
    return words


def merge_trigger_words(file_words: list[str], db_words: list[str]) -> list[str]:
    normalized_db_words = [word.lower() for word in db_words]
    return sorted(set(file_words) | set(normalized_db_words))


def contains_trigger_word(text: str, trigger_words: list[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in trigger_words)


def compute_violation(
    current_count: int,
    last_violation_at: Optional[datetime],
    reset_days: int,
    now: datetime,
) -> tuple[int, str]:
    if last_violation_at is not None and reset_days > 0:
        if now - last_violation_at > timedelta(days=reset_days):
            current_count = 0

    new_count = current_count + 1

    if new_count == 1:
        return new_count, "warn"
    if new_count == 2:
        return new_count, "mute"
    return 0, "kick"
