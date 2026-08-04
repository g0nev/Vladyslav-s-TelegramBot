# Проактивные сообщения бота в чат — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот иногда сам пишет в чат непрошено (не в ответ на команду/нарушение), реагируя на последние N сообщений в духе `/setpersona`-персоны — по расписанию (раз в N минут) или по вероятности на сообщение, настраиваемо на чат.

**Architecture:** Новый in-memory буфер последних сообщений чата (`proactive/buffer.py`) кормит контекстом два независимых, взаимоисключающих триггера: APScheduler-job на interval-режим (`scheduler/proactive.py`, по образцу `scheduler/broadcaster.py`) и inline-проверка вероятности в обработчике каждого группового сообщения (`moderation/handlers.py`). Оба вызывают общий AI-генератор реплики (`ai/openrouter_client.py::generate_proactive_message`, по образцу `generate_violation_reaction`). Существующая логика модерации (`compute_violation`, эскалация наказаний) не меняется.

**Tech Stack:** Python, aiogram, APScheduler, pytest, aiohttp/OpenRouter (уже используются в проекте).

## Global Constraints

- Спека: `docs/superpowers/specs/2026-08-04-proactive-persona-chat-design.md`.
- Ровно один режим на чат: `proactive_mode` ∈ `{'off', 'interval', 'probability'}`. `off` — значение по умолчанию для всех чатов.
- Функция работает только если у чата задана персона (`repository.get_persona`) — без персоны проактивность молчит, даже если `proactive_mode != 'off'`.
- Контекст — последние N сообщений чата, N настраивается отдельно (`proactive_context_size`, диапазон 1–10), не хардкод «последнее сообщение».
- Буфер сообщений — только in-memory (`proactive/buffer.py`), не персистится в БД. Обнуляется при рестарте бота — осознанно принятый компромисс.
- Общий минимальный кулдаун между двумя проактивными отправками в одном чате — константа кода `proactive.buffer.MIN_COOLDOWN_SECONDS`, не настройка per-chat.
- Существующая эскалация наказаний (`moderation/logic.py::compute_violation`, `handle_moderated_message`) не меняется. `/ask`-tool-calling (`ask_ai_with_tools`, `META_TOOLS`, `execute_tool`) не меняется.
- Не проверяем/не модерируем сгенерированный ботом текст перед отправкой — тот же принцип доверия, что уже принят для `generate_violation_reaction`.
- Новые колонки БД — только через `_MIGRATION_COLUMNS` в `db/repository.py` (тот же механизм `ALTER TABLE ... ADD COLUMN`, что и у `persona`/`mute_minutes`), не через `db/models.sql`.

---

## File Structure

- Create: `proactive/__init__.py` — пустой, делает `proactive` пакетом (по образцу `ai/__init__.py`, `scheduler/__init__.py`).
- Create: `proactive/buffer.py` — in-memory кольцевой буфер сообщений на чат + состояние кулдауна/последнего срабатывания.
- Create: `scheduler/proactive.py` — interval-режим: APScheduler job на чат, по образцу `scheduler/broadcaster.py`.
- Modify: `db/repository.py` — новые колонки `chat_settings` + методы доступа к proactive-настройкам.
- Modify: `ai/openrouter_client.py` — новая функция `generate_proactive_message`.
- Modify: `moderation/handlers.py` — запись каждого сообщения в буфер + probability-хук.
- Modify: `admin/commands.py` — команды `/setproactive`, `/setproactivecontext`.
- Modify: `admin/bot_commands.py` — описания новых команд в `BOT_COMMANDS`.
- Modify: `bot.py` — регистрация `load_scheduled_proactive` при старте.
- Modify тесты: `tests/test_proactive_buffer.py` (новый), `tests/test_repository.py`, `tests/test_openrouter_client.py`, `tests/test_scheduler_proactive.py` (новый), `tests/test_moderation_handlers.py`, `tests/test_admin_commands.py`, `tests/test_bot_commands.py`.

Новых таблиц БД нет — только новые колонки в существующей `chat_settings`.

---

### Task 1: Буфер последних сообщений (`proactive/buffer.py`)

**Files:**
- Create: `proactive/__init__.py`
- Create: `proactive/buffer.py`
- Test: `tests/test_proactive_buffer.py`

**Interfaces:**
- Consumes: ничего нового (стандартная библиотека: `collections.deque`, `time.monotonic`, `dataclasses`).
- Produces:
  - `MIN_COOLDOWN_SECONDS: float` — константа
  - `record_message(chat_id: int, author: str, text: str, message_id: int) -> None`
  - `get_recent(chat_id: int, n: int) -> list[str]`
  - `latest_message_id(chat_id: int) -> Optional[int]`
  - `has_new_since_last_fire(chat_id: int) -> bool`
  - `mark_fired(chat_id: int, message_id: int) -> None`
  - `cooldown_elapsed(chat_id: int) -> bool`

  Используется в Task 4 (`scheduler/proactive.py`) и Task 5 (`moderation/handlers.py`).

- [ ] **Step 1: Создать пакет и написать падающие тесты**

Создать пустой файл `proactive/__init__.py`.

Создать `tests/test_proactive_buffer.py`:

```python
import pytest

import proactive.buffer as buffer


@pytest.fixture(autouse=True)
def clear_buffer():
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()
    yield
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()


def test_get_recent_empty_chat_returns_empty_list():
    assert buffer.get_recent(chat_id=1, n=3) == []


def test_record_message_then_get_recent_returns_formatted_lines():
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)
    buffer.record_message(chat_id=1, author="Боря", text="как дела", message_id=2)

    assert buffer.get_recent(chat_id=1, n=2) == ["Аня: привет", "Боря: как дела"]


def test_get_recent_returns_at_most_n_most_recent_in_order():
    for i in range(5):
        buffer.record_message(chat_id=1, author="Аня", text=f"msg{i}", message_id=i)

    assert buffer.get_recent(chat_id=1, n=2) == ["Аня: msg3", "Аня: msg4"]


def test_buffer_caps_at_twenty_oldest_dropped():
    for i in range(25):
        buffer.record_message(chat_id=1, author="Аня", text=f"msg{i}", message_id=i)

    recent = buffer.get_recent(chat_id=1, n=20)
    assert recent[0] == "Аня: msg5"
    assert recent[-1] == "Аня: msg24"


def test_buffers_are_independent_per_chat():
    buffer.record_message(chat_id=1, author="Аня", text="чат 1", message_id=1)
    buffer.record_message(chat_id=2, author="Боря", text="чат 2", message_id=1)

    assert buffer.get_recent(chat_id=1, n=5) == ["Аня: чат 1"]
    assert buffer.get_recent(chat_id=2, n=5) == ["Боря: чат 2"]


def test_latest_message_id_returns_none_for_unknown_chat():
    assert buffer.latest_message_id(chat_id=999) is None


def test_latest_message_id_returns_newest():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=10)
    buffer.record_message(chat_id=1, author="Аня", text="b", message_id=11)

    assert buffer.latest_message_id(chat_id=1) == 11


def test_has_new_since_last_fire_false_for_unknown_chat():
    assert buffer.has_new_since_last_fire(chat_id=999) is False


def test_has_new_since_last_fire_true_before_any_fire():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)

    assert buffer.has_new_since_last_fire(chat_id=1) is True


def test_has_new_since_last_fire_false_after_mark_fired_with_latest():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)

    assert buffer.has_new_since_last_fire(chat_id=1) is False


def test_has_new_since_last_fire_true_again_after_new_message():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)
    buffer.record_message(chat_id=1, author="Аня", text="b", message_id=2)

    assert buffer.has_new_since_last_fire(chat_id=1) is True


def test_cooldown_elapsed_true_before_any_fire():
    assert buffer.cooldown_elapsed(chat_id=1) is True


def test_cooldown_elapsed_false_immediately_after_mark_fired():
    buffer.mark_fired(chat_id=1, message_id=1)

    assert buffer.cooldown_elapsed(chat_id=1) is False


def test_cooldown_elapsed_true_after_floor_seconds_pass(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(buffer, "monotonic", lambda: fake_time[0])

    buffer.mark_fired(chat_id=1, message_id=1)
    fake_time[0] += buffer.MIN_COOLDOWN_SECONDS + 1

    assert buffer.cooldown_elapsed(chat_id=1) is True
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_proactive_buffer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proactive.buffer'` (модуль ещё не создан).

- [ ] **Step 3: Реализовать `proactive/buffer.py`**

```python
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
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_proactive_buffer.py -v`
Expected: PASS — все 15 тестов.

- [ ] **Step 5: Commit**

```bash
git add proactive/__init__.py proactive/buffer.py tests/test_proactive_buffer.py
git commit -m "$(cat <<'EOF'
Add in-memory recent-message buffer for proactive chat replies

The bot never stored any message history — proactive replies need
something to react to. This adds a per-chat ring buffer (in-memory,
cap 20) plus last-fired tracking used by both trigger modes to decide
"is there anything new to react to" and "did we just speak recently".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Настройки БД для проактивности (`db/repository.py`)

**Files:**
- Modify: `db/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: ничего нового.
- Produces:
  - `get_proactive_settings(chat_id: int) -> tuple[str, int, float, int]` — `(mode, interval_min, probability, context_size)`
  - `set_proactive_off(chat_id: int) -> None`
  - `set_proactive_interval(chat_id: int, minutes: int) -> None`
  - `set_proactive_probability(chat_id: int, probability: float) -> None`
  - `set_proactive_context_size(chat_id: int, size: int) -> None`
  - `list_active_proactive_interval_chats() -> list[tuple[int, int]]`

  Используется в Task 4 (`scheduler/proactive.py`), Task 5 (`moderation/handlers.py`), Task 6 (`admin/commands.py`).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_repository.py`:

```python
async def test_proactive_settings_default(repo):
    assert await repo.get_proactive_settings(chat_id=1) == ("off", 0, 0.0, 3)


async def test_set_proactive_interval_updates_mode_and_minutes(repo):
    await repo.set_proactive_interval(chat_id=1, minutes=20)

    assert await repo.get_proactive_settings(chat_id=1) == ("interval", 20, 0.0, 3)


async def test_set_proactive_probability_updates_mode_and_probability(repo):
    await repo.set_proactive_probability(chat_id=1, probability=0.05)

    assert await repo.get_proactive_settings(chat_id=1) == ("probability", 0, 0.05, 3)


async def test_set_proactive_off_resets_mode_and_values(repo):
    await repo.set_proactive_interval(chat_id=1, minutes=20)

    await repo.set_proactive_off(chat_id=1)

    assert await repo.get_proactive_settings(chat_id=1) == ("off", 0, 0.0, 3)


async def test_set_proactive_context_size(repo):
    await repo.set_proactive_context_size(chat_id=1, size=7)

    assert await repo.get_proactive_settings(chat_id=1) == ("off", 0, 0.0, 7)


async def test_switching_from_interval_to_probability_clears_interval_minutes(repo):
    await repo.set_proactive_interval(chat_id=1, minutes=20)

    await repo.set_proactive_probability(chat_id=1, probability=0.1)

    assert await repo.get_proactive_settings(chat_id=1) == ("probability", 0, 0.1, 3)


async def test_switching_from_probability_to_interval_clears_probability(repo):
    await repo.set_proactive_probability(chat_id=1, probability=0.1)

    await repo.set_proactive_interval(chat_id=1, minutes=20)

    assert await repo.get_proactive_settings(chat_id=1) == ("interval", 20, 0.0, 3)


async def test_list_active_proactive_interval_chats_only_interval_mode_positive_minutes(repo):
    await repo.set_proactive_interval(chat_id=1, minutes=20)
    await repo.set_proactive_probability(chat_id=2, probability=0.1)
    await repo.set_proactive_interval(chat_id=3, minutes=20)
    await repo.set_proactive_off(chat_id=3)

    chats = await repo.list_active_proactive_interval_chats()

    assert chats == [(1, 20)]
```

Также расширить существующий тест миграции (найти `test_migration_adds_columns_to_preexisting_db` в `tests/test_repository.py`, добавить строку перед `await reopened_repo.close()`):

```python
    assert await reopened_repo.get_proactive_settings(chat_id=1) == ("off", 0, 0.0, 3)
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_repository.py -k proactive -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'get_proactive_settings'` (и аналогично для остальных новых методов/расширенного теста миграции).

- [ ] **Step 3: Добавить колонки и методы в `db/repository.py`**

Изменить `_MIGRATION_COLUMNS` (строки 11–20):

```python
_MIGRATION_COLUMNS = {
    "warn_message": "TEXT",
    "mute_message": "TEXT",
    "kick_message": "TEXT",
    "saved_permissions_json": "TEXT",
    "last_invite_link": "TEXT",
    "mute_minutes": "INTEGER NOT NULL DEFAULT 5",
    "kick_after_violation": "INTEGER NOT NULL DEFAULT 3",
    "persona": "TEXT",
    "proactive_mode": "TEXT NOT NULL DEFAULT 'off'",
    "proactive_interval_min": "INTEGER NOT NULL DEFAULT 0",
    "proactive_probability": "REAL NOT NULL DEFAULT 0.0",
    "proactive_context_size": "INTEGER NOT NULL DEFAULT 3",
}
```

Добавить в конец класса `Repository` (после `set_persona`):

```python
    async def get_proactive_settings(self, chat_id: int) -> tuple[str, int, float, int]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT proactive_mode, proactive_interval_min, proactive_probability, "
            "proactive_context_size FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2], row[3])

    async def set_proactive_off(self, chat_id: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'off', proactive_interval_min = 0, "
            "proactive_probability = 0.0 WHERE chat_id = ?",
            (chat_id,),
        )
        await self._conn.commit()

    async def set_proactive_interval(self, chat_id: int, minutes: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'interval', "
            "proactive_interval_min = ?, proactive_probability = 0.0 WHERE chat_id = ?",
            (minutes, chat_id),
        )
        await self._conn.commit()

    async def set_proactive_probability(self, chat_id: int, probability: float) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'probability', "
            "proactive_probability = ?, proactive_interval_min = 0 WHERE chat_id = ?",
            (probability, chat_id),
        )
        await self._conn.commit()

    async def set_proactive_context_size(self, chat_id: int, size: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_context_size = ? WHERE chat_id = ?",
            (size, chat_id),
        )
        await self._conn.commit()

    async def list_active_proactive_interval_chats(self) -> list[tuple[int, int]]:
        cursor = await self._conn.execute(
            "SELECT chat_id, proactive_interval_min FROM chat_settings "
            "WHERE proactive_mode = 'interval' AND proactive_interval_min > 0"
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_repository.py -v`
Expected: PASS — весь файл, включая новые тесты и расширенный тест миграции.

- [ ] **Step 5: Commit**

```bash
git add db/repository.py tests/test_repository.py
git commit -m "$(cat <<'EOF'
Add proactive-chat settings columns and Repository accessors

Four new chat_settings columns (mode, interval, probability, context
size) via the existing ALTER TABLE migration mechanism. Mode is
enforced mutually-exclusive at the setter level: switching to interval
clears probability and vice versa, so list_active_proactive_interval_chats
never double-fires a chat that's actually in probability mode.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: AI-генератор проактивной реплики (`ai/openrouter_client.py`)

**Files:**
- Modify: `ai/openrouter_client.py`
- Test: `tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: `config.OPENROUTER_API_KEY`, `config.OPENROUTER_MODEL`, `config.OPENROUTER_MAX_TOKENS`, `OPENROUTER_URL` (уже существуют в файле).
- Produces: `generate_proactive_message(persona: str, recent_messages: list[str]) -> Optional[str]`.

  Используется в Task 4 (`scheduler/proactive.py`) и Task 5 (`moderation/handlers.py`).

- [ ] **Step 1: Написать падающие тесты**

Добавить `generate_proactive_message` в импорт из `ai.openrouter_client` в начале `tests/test_openrouter_client.py` (строка со списком импортов — добавить в алфавитном порядке рядом с `generate_violation_reaction`):

```python
from ai.openrouter_client import (
    CALL_TOOL,
    META_TOOLS,
    READ_GENERAL_INFO,
    READ_TOOLS_REFERENCE,
    SYSTEM_PROMPT,
    AIResponse,
    AIUnavailableError,
    ask_ai,
    ask_ai_with_tools,
    build_general_info,
    build_tools_reference,
    generate_proactive_message,
    generate_violation_reaction,
)
```

Добавить в конец файла (переиспользует уже существующий в файле хелпер `_make_session_cm`):

```python
async def test_generate_proactive_message_returns_text_on_success(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "  О, интересная тема!  "}}]}
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: как дела"])

    assert result == "О, интересная тема!"


async def test_generate_proactive_message_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 500

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_client_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("boom"))

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_empty_content(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "   "}}]})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"unexpected": "shape"})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_json_decode_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_includes_persona_and_recent_messages_in_prompt(
    monkeypatch,
):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "Ок"}}]})

    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        await generate_proactive_message(
            "Дерзкий стиль и юмор", ["Аня: го в кино", "Боря: не хочу"]
        )

    payload = session.post.call_args.kwargs["json"]
    prompt = payload["messages"][0]["content"]
    assert "Дерзкий стиль и юмор" in prompt
    assert "Аня: го в кино" in prompt
    assert "Боря: не хочу" in prompt


async def test_generate_proactive_message_handles_empty_recent_messages(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "Привет!"}}]})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", [])

    assert result == "Привет!"
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_openrouter_client.py -k proactive_message -v`
Expected: FAIL — `ImportError: cannot import name 'generate_proactive_message' from 'ai.openrouter_client'`.

- [ ] **Step 3: Реализовать `generate_proactive_message`**

Добавить в конец `ai/openrouter_client.py` (после `generate_violation_reaction`):

```python
async def generate_proactive_message(persona: str, recent_messages: list[str]) -> Optional[str]:
    """Single non-tool completion call for an unprompted chat reaction.

    Swallows every failure mode (missing key, non-200, network error,
    timeout, malformed/empty response) into None so the caller simply
    skips sending anything.
    """
    if not config.OPENROUTER_API_KEY:
        return None

    conversation = "\n".join(recent_messages) if recent_messages else "(сообщений пока не было)"
    task_prompt = (
        f"Характер бота в этом чате: {persona}\n"
        f"Вот последние сообщения переписки:\n{conversation}\n\n"
        "Напиши одну короткую (1-2 предложения) реплику в этот разговор от своего имени, "
        "в заданном характере — как будто ты участник чата, который решил вставить своё "
        "слово. Не здоровайся, не представляйся, не резюмируй переписку — просто "
        "естественная реплика по теме."
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={
                    "model": config.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": task_prompt}],
                    "max_tokens": config.OPENROUTER_MAX_TOKENS,
                },
                timeout=_REACTION_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None

    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return None

    return text or None
```

- [ ] **Step 4: Прогнать весь файл тестов, убедиться что всё зелёное**

Run: `pytest tests/test_openrouter_client.py -v`
Expected: PASS — все тесты файла, включая 10 новых.

- [ ] **Step 5: Commit**

```bash
git add ai/openrouter_client.py tests/test_openrouter_client.py
git commit -m "$(cat <<'EOF'
Add generate_proactive_message for unprompted chat reactions

Same shape as generate_violation_reaction (single non-tool completion,
10s timeout, every failure mode swallowed to None) but takes recent
chat context instead of a punishment outcome, and asks for a natural
one-line reply rather than a moderation reaction.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Interval-режим (`scheduler/proactive.py`)

**Files:**
- Create: `scheduler/proactive.py`
- Modify: `bot.py`
- Test: `tests/test_scheduler_proactive.py`

**Interfaces:**
- Consumes: `proactive.buffer` (Task 1), `Repository.get_persona`/`get_proactive_settings`/`list_active_proactive_interval_chats` (Task 2), `ai.openrouter_client.generate_proactive_message` (Task 3).
- Produces:
  - `schedule_chat_proactive(scheduler, bot, repository, chat_id: int, interval_minutes: int) -> None`
  - `load_scheduled_proactive(scheduler, bot, repository) -> None`

  `schedule_chat_proactive` используется в Task 6 (`admin/commands.py`). `load_scheduled_proactive` вызывается из `bot.py`.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_scheduler_proactive.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import proactive.buffer as buffer
from db.repository import Repository
from scheduler.proactive import (
    _scheduled_proactive_job,
    load_scheduled_proactive,
    schedule_chat_proactive,
)


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


@pytest.fixture
def scheduler():
    sched = AsyncIOScheduler()
    yield sched
    if sched.running:
        sched.shutdown(wait=False)


@pytest.fixture(autouse=True)
def clear_buffer():
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()
    yield
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()


async def test_schedule_chat_proactive_registers_job(repo, scheduler):
    bot = AsyncMock()

    schedule_chat_proactive(scheduler, bot, repo, chat_id=1, interval_minutes=20)

    assert scheduler.get_job("proactive_1") is not None


async def test_schedule_chat_proactive_removes_job_when_zero(repo, scheduler):
    bot = AsyncMock()
    schedule_chat_proactive(scheduler, bot, repo, chat_id=1, interval_minutes=20)

    schedule_chat_proactive(scheduler, bot, repo, chat_id=1, interval_minutes=0)

    assert scheduler.get_job("proactive_1") is None


async def test_load_scheduled_proactive_registers_only_interval_mode_chats(repo, scheduler):
    bot = AsyncMock()
    await repo.set_proactive_interval(chat_id=1, minutes=15)
    await repo.set_proactive_probability(chat_id=2, probability=0.05)

    await load_scheduled_proactive(scheduler, bot, repo)

    assert scheduler.get_job("proactive_1") is not None
    assert scheduler.get_job("proactive_2") is None


async def test_scheduled_job_skips_without_persona(repo, scheduler):
    bot = AsyncMock()
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)

    await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_scheduled_job_skips_when_no_new_messages(repo, scheduler):
    bot = AsyncMock()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)

    await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_scheduled_job_skips_on_cooldown(repo, scheduler):
    bot = AsyncMock()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="Аня", text="раз", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)
    buffer.record_message(chat_id=1, author="Аня", text="два", message_id=2)

    await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_scheduled_job_sends_and_marks_fired_on_success(repo, scheduler):
    bot = AsyncMock()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)

    with patch(
        "scheduler.proactive.generate_proactive_message",
        AsyncMock(return_value="О, о чём базар?"),
    ):
        await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    bot.send_message.assert_awaited_once_with(1, "О, о чём базар?")
    assert buffer.has_new_since_last_fire(chat_id=1) is False


async def test_scheduled_job_skips_send_when_generation_returns_none(repo, scheduler):
    bot = AsyncMock()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)

    with patch(
        "scheduler.proactive.generate_proactive_message", AsyncMock(return_value=None)
    ):
        await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_scheduled_job_removes_job_on_api_error(repo, scheduler):
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramAPIError(method=None, message="bot was kicked")
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)
    schedule_chat_proactive(scheduler, bot, repo, chat_id=1, interval_minutes=20)

    with patch(
        "scheduler.proactive.generate_proactive_message",
        AsyncMock(return_value="реакция"),
    ):
        await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    assert scheduler.get_job("proactive_1") is None


async def test_scheduled_job_uses_configured_context_size(repo, scheduler):
    bot = AsyncMock()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_context_size(chat_id=1, size=1)
    buffer.record_message(chat_id=1, author="Аня", text="старое", message_id=1)
    buffer.record_message(chat_id=1, author="Боря", text="новое", message_id=2)

    with patch(
        "scheduler.proactive.generate_proactive_message", AsyncMock(return_value="ок")
    ) as mock_generate:
        await _scheduled_proactive_job(scheduler, bot, repo, chat_id=1)

    mock_generate.assert_awaited_once_with("Дерзкий стиль", ["Боря: новое"])
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_scheduler_proactive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scheduler.proactive'`.

- [ ] **Step 3: Реализовать `scheduler/proactive.py`**

```python
from __future__ import annotations

import html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai.openrouter_client import generate_proactive_message
from db.repository import Repository
from proactive import buffer


def _job_id(chat_id: int) -> str:
    return f"proactive_{chat_id}"


async def _scheduled_proactive_job(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository, chat_id: int
) -> None:
    persona = await repository.get_persona(chat_id)
    if not persona:
        return
    if not buffer.has_new_since_last_fire(chat_id):
        return
    if not buffer.cooldown_elapsed(chat_id):
        return

    _, _, _, context_size = await repository.get_proactive_settings(chat_id)
    recent = buffer.get_recent(chat_id, context_size)
    text = await generate_proactive_message(persona, recent)
    if not text:
        return

    try:
        await bot.send_message(chat_id, html.escape(text))
    except TelegramAPIError:
        job_id = _job_id(chat_id)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        return

    latest_id = buffer.latest_message_id(chat_id)
    if latest_id is not None:
        buffer.mark_fired(chat_id, latest_id)


def schedule_chat_proactive(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    repository: Repository,
    chat_id: int,
    interval_minutes: int,
) -> None:
    job_id = _job_id(chat_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if interval_minutes <= 0:
        return
    scheduler.add_job(
        _scheduled_proactive_job,
        "interval",
        minutes=interval_minutes,
        id=job_id,
        args=[scheduler, bot, repository, chat_id],
        replace_existing=True,
    )


async def load_scheduled_proactive(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository
) -> None:
    for chat_id, interval_minutes in await repository.list_active_proactive_interval_chats():
        schedule_chat_proactive(scheduler, bot, repository, chat_id, interval_minutes)
```

Изменить `bot.py`: добавить импорт (после строки `from scheduler.broadcaster import load_scheduled_broadcasts`):

```python
from scheduler.proactive import load_scheduled_proactive
```

И вызов (после строки `await load_scheduled_broadcasts(scheduler, bot, repository)`, перед `scheduler.start()`):

```python
    await load_scheduled_broadcasts(scheduler, bot, repository)
    await load_scheduled_proactive(scheduler, bot, repository)
    scheduler.start()
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_scheduler_proactive.py -v`
Expected: PASS — все 10 тестов.

- [ ] **Step 5: Commit**

```bash
git add scheduler/proactive.py bot.py tests/test_scheduler_proactive.py
git commit -m "$(cat <<'EOF'
Add interval-mode scheduler for proactive chat replies

Mirrors scheduler/broadcaster.py exactly: one APScheduler job per
chat, replace_existing on reschedule, job removes itself on
TelegramAPIError (bot kicked). Skips firing when there's no persona,
no new messages since the last fire, or the shared cooldown hasn't
elapsed. Wired into bot.py startup alongside load_scheduled_broadcasts.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Запись в буфер + probability-режим (`moderation/handlers.py`)

**Files:**
- Modify: `moderation/handlers.py`
- Test: `tests/test_moderation_handlers.py`

**Interfaces:**
- Consumes: `proactive.buffer` (Task 1), `Repository.get_persona`/`get_proactive_settings` (Task 2), `ai.openrouter_client.generate_proactive_message` (Task 3).
- Produces: `_maybe_send_proactive_reaction(message, bot, repository) -> None` — вызывается только из `on_group_message` в этом же файле, наружу не экспортируется.

**Важное архитектурное уточнение к спеке:** в спеке пример кода вероятностной проверки был показан как часть `handle_moderated_message`. Но `handle_moderated_message` содержит ранние `return` (нет триггер-слова, отправитель — админ, нет прав на mute/kick), после которых код спеки не выполнился бы — а по спеке кубик должен бросаться «для любого отправителя (включая админов)», независимо от того, было ли применено наказание. Поэтому вероятностная проверка вынесена в отдельную функцию `_maybe_send_proactive_reaction`, которую `on_group_message` вызывает отдельным вызовом после `handle_moderated_message` — так она гарантированно выполняется для каждого сообщения. Запись в буфер (`buffer.record_message`) при этом остаётся внутри `handle_moderated_message`, в самом начале — до admin-bypass, как и написано в спеке.

- [ ] **Step 1: Обновить тестовый хелпер и написать падающие тесты**

В `tests/test_moderation_handlers.py` заменить хелпер `make_message` (строки 18–25):

```python
def make_message(text, user_id=100, chat_id=1, message_id=1):
    from_user = SimpleNamespace(
        id=user_id, mention_html=lambda: f"User{user_id}", full_name=f"User{user_id}"
    )
    return SimpleNamespace(
        text=text,
        from_user=from_user,
        chat=SimpleNamespace(id=chat_id),
        message_id=message_id,
        answer=AsyncMock(),
    )
```

Заменить блок импортов в начале файла:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError

import moderation.handlers as handlers
import proactive.buffer as buffer
from db.repository import Repository
from moderation.handlers import (
    _maybe_send_proactive_reaction,
    handle_moderated_message,
    on_group_message,
)
```

Добавить после существующей фикстуры `repo` (после строки `await repository.close()`):

```python
@pytest.fixture(autouse=True)
def clear_buffer():
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()
    yield
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()
```

Добавить в конец файла:

```python
async def test_message_is_recorded_into_proactive_buffer(repo):
    bot = await make_bot()
    message = make_message("обычное сообщение", message_id=42)

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    assert buffer.get_recent(chat_id=1, n=1) == ["User100: обычное сообщение"]


async def test_admin_message_is_still_recorded_into_buffer(repo):
    bot = await make_bot(admin_ids={100})
    message = make_message("сообщение админа", message_id=7)

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    assert buffer.get_recent(chat_id=1, n=1) == ["User100: сообщение админа"]


async def test_proactive_reaction_skipped_when_mode_is_off(repo):
    bot = await make_bot()
    message = make_message("привет всем")
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    buffer.record_message(chat_id=1, author="User100", text="привет всем", message_id=1)

    await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_not_called()


async def test_proactive_reaction_skipped_without_persona(repo):
    bot = await make_bot()
    message = make_message("привет всем")
    await repo.set_proactive_probability(chat_id=1, probability=1.0)

    await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_not_called()


async def test_proactive_reaction_skipped_when_dice_roll_fails(repo, monkeypatch):
    bot = await make_bot()
    message = make_message("привет всем")
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=0.01)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.5)

    await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_not_called()


async def test_proactive_reaction_sent_on_dice_win(repo, monkeypatch):
    bot = await make_bot()
    message = make_message("о чём поговорим", message_id=5)
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=0.5)
    buffer.record_message(chat_id=1, author="User100", text="о чём поговорим", message_id=5)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.1)

    with patch(
        "moderation.handlers.generate_proactive_message",
        AsyncMock(return_value="О, интересная тема!"),
    ):
        await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_awaited_once_with("О, интересная тема!")


async def test_proactive_reaction_skipped_on_cooldown(repo, monkeypatch):
    bot = await make_bot()
    message = make_message("привет", message_id=2)
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=1.0)
    buffer.mark_fired(chat_id=1, message_id=1)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.0)

    await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_not_called()


async def test_proactive_reaction_not_sent_when_generation_returns_none(repo, monkeypatch):
    bot = await make_bot()
    message = make_message("привет", message_id=3)
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=1.0)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.0)

    with patch(
        "moderation.handlers.generate_proactive_message", AsyncMock(return_value=None)
    ):
        await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_not_called()


async def test_proactive_reaction_fires_for_admin_sender_too(repo, monkeypatch):
    bot = await make_bot(admin_ids={100})
    message = make_message("привет", message_id=4)
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=1.0)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.0)

    with patch(
        "moderation.handlers.generate_proactive_message",
        AsyncMock(return_value="реплика"),
    ):
        await _maybe_send_proactive_reaction(message, bot, repo)

    message.answer.assert_awaited_once_with("реплика")


async def test_on_group_message_wires_both_moderation_and_proactive_paths(repo, monkeypatch):
    bot = await make_bot()
    message = make_message("обычное сообщение", message_id=9)
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    await repo.set_proactive_probability(chat_id=1, probability=1.0)
    monkeypatch.setattr(handlers.random, "random", lambda: 0.0)

    with patch(
        "moderation.handlers.generate_proactive_message",
        AsyncMock(return_value="Реплика бота"),
    ):
        await on_group_message(message, bot, repo, default_trigger_words=[])

    message.answer.assert_awaited_once_with("Реплика бота")
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_moderation_handlers.py -v`
Expected: FAIL — `ImportError: cannot import name '_maybe_send_proactive_reaction' from 'moderation.handlers'` (и тесты записи в буфер падают, т.к. `handle_moderated_message` ещё не пишет в буфер).

- [ ] **Step 3: Реализовать запись в буфер и probability-хук**

В `moderation/handlers.py` изменить блок импортов (строки 1–19):

```python
from __future__ import annotations

import html
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message

from admin.permissions import is_admin
from ai.openrouter_client import generate_proactive_message, generate_violation_reaction
from db.repository import Repository
from moderation.logic import (
    compute_violation,
    contains_trigger_word,
    format_punishment_message,
    merge_trigger_words,
)
from proactive import buffer
```

В `handle_moderated_message` добавить запись в буфер сразу после guard-условия (было: `if message.from_user is None or message.text is None: return` — после него сразу `db_words = await repository.list_trigger_words(...)`). Новый порядок:

```python
async def handle_moderated_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    if message.from_user is None or message.text is None:
        return

    buffer.record_message(
        message.chat.id, message.from_user.full_name, message.text, message.message_id
    )

    if await is_admin(bot, message.chat.id, message.from_user.id):
        return

    db_words = await repository.list_trigger_words(message.chat.id)
    ...
```

(остальное тело `handle_moderated_message` без изменений).

Добавить новую функцию после `handle_moderated_message`, перед `@router.message(...)` / `on_group_message`:

```python
async def _maybe_send_proactive_reaction(
    message: Message, bot: Bot, repository: Repository
) -> None:
    if message.from_user is None or message.text is None:
        return

    mode, _, probability, context_size = await repository.get_proactive_settings(
        message.chat.id
    )
    if mode != "probability":
        return

    persona = await repository.get_persona(message.chat.id)
    if not persona:
        return

    if random.random() >= probability:
        return
    if not buffer.cooldown_elapsed(message.chat.id):
        return

    recent = buffer.get_recent(message.chat.id, context_size)
    text = await generate_proactive_message(persona, recent)
    if not text:
        return

    try:
        await message.answer(html.escape(text))
    except TelegramAPIError:
        return

    latest_id = buffer.latest_message_id(message.chat.id)
    if latest_id is not None:
        buffer.mark_fired(message.chat.id, latest_id)
```

Изменить `on_group_message`, добавив второй вызов:

```python
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def on_group_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    await handle_moderated_message(message, bot, repository, default_trigger_words)
    await _maybe_send_proactive_reaction(message, bot, repository)
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_moderation_handlers.py -v`
Expected: PASS — все тесты файла (существующие + новые).

- [ ] **Step 5: Commit**

```bash
git add moderation/handlers.py tests/test_moderation_handlers.py
git commit -m "$(cat <<'EOF'
Wire message buffer recording and probability-mode proactive replies

Every group text message now feeds the recent-message buffer, before
the admin bypass, so context stays warm even for messages that never
trigger moderation. The probability trigger lives in its own function
called as a sibling of handle_moderated_message (not nested inside
it), because handle_moderated_message's early returns (no trigger
word, sender is admin, missing mute/kick permissions) would otherwise
prevent the dice roll from firing for the admin/no-violation case the
design explicitly calls for.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Команды админа `/setproactive`, `/setproactivecontext`

**Files:**
- Modify: `admin/commands.py`
- Modify: `admin/bot_commands.py`
- Test: `tests/test_admin_commands.py`
- Test: `tests/test_bot_commands.py`

**Interfaces:**
- Consumes: `Repository.set_proactive_off`/`set_proactive_interval`/`set_proactive_probability`/`set_proactive_context_size`/`get_proactive_settings` (Task 2), `scheduler.proactive.schedule_chat_proactive` (Task 4).
- Produces: команды `/setproactive`, `/setproactivecontext` (конечная точка интеграции, наружу ничего не экспортируется).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_admin_commands.py`:

```python
async def test_setproactive_requires_admin(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=2)

    await commands.cmd_setproactive(message, cmd("interval 10"), bot, repo, scheduler)

    mode, *_ = await repo.get_proactive_settings(1)
    assert mode == "off"
    assert scheduler.get_job("proactive_1") is None


async def test_setproactive_interval_sets_mode_and_schedules_job(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd("interval 10"), bot, repo, scheduler)

    assert await repo.get_proactive_settings(1) == ("interval", 10, 0.0, 3)
    assert scheduler.get_job("proactive_1") is not None


async def test_setproactive_interval_rejects_zero(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd("interval 0"), bot, repo, scheduler)

    mode, *_ = await repo.get_proactive_settings(1)
    assert mode == "off"


async def test_setproactive_chance_sets_mode_and_probability(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd("chance 5"), bot, repo, scheduler)

    assert await repo.get_proactive_settings(1) == ("probability", 0, 0.05, 3)


async def test_setproactive_chance_rejects_out_of_range(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd("chance 150"), bot, repo, scheduler)

    mode, *_ = await repo.get_proactive_settings(1)
    assert mode == "off"


async def test_setproactive_off_removes_scheduled_job(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)
    await commands.cmd_setproactive(message, cmd("interval 10"), bot, repo, scheduler)

    await commands.cmd_setproactive(message, cmd("off"), bot, repo, scheduler)

    mode, *_ = await repo.get_proactive_settings(1)
    assert mode == "off"
    assert scheduler.get_job("proactive_1") is None


async def test_setproactive_switching_from_interval_to_chance_removes_job(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)
    await commands.cmd_setproactive(message, cmd("interval 10"), bot, repo, scheduler)

    await commands.cmd_setproactive(message, cmd("chance 5"), bot, repo, scheduler)

    assert await repo.get_proactive_settings(1) == ("probability", 0, 0.05, 3)
    assert scheduler.get_job("proactive_1") is None


async def test_setproactive_unknown_subcommand_shows_usage_and_changes_nothing(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd("banana"), bot, repo, scheduler)

    mode, *_ = await repo.get_proactive_settings(1)
    assert mode == "off"
    message.answer.assert_awaited_once()


async def test_setproactive_no_args_shows_usage(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactive(message, cmd(None), bot, repo, scheduler)

    message.answer.assert_awaited_once()


async def test_setproactivecontext_updates_value(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactivecontext(message, cmd("5"), bot, repo)

    _, _, _, context_size = await repo.get_proactive_settings(1)
    assert context_size == 5


async def test_setproactivecontext_rejects_out_of_range(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setproactivecontext(message, cmd("11"), bot, repo)

    _, _, _, context_size = await repo.get_proactive_settings(1)
    assert context_size == 3


async def test_setproactivecontext_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=2)

    await commands.cmd_setproactivecontext(message, cmd("5"), bot, repo)

    _, _, _, context_size = await repo.get_proactive_settings(1)
    assert context_size == 3
```

Изменить `tests/test_bot_commands.py`, добавив в множество `names` (внутри `test_bot_commands_cover_all_commands`) две строки:

```python
        "setproactive",
        "setproactivecontext",
```

(в любое место множества — порядок не важен, сравнение множествами).

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_admin_commands.py -k proactive -v`
Expected: FAIL — `AttributeError: module 'admin.commands' has no attribute 'cmd_setproactive'`.

Run: `pytest tests/test_bot_commands.py -v`
Expected: FAIL — `test_bot_commands_cover_all_commands` падает (множества не совпадают, `setproactive`/`setproactivecontext` ожидаются, но их нет в `BOT_COMMANDS`).

- [ ] **Step 3: Реализовать команды**

В `admin/commands.py` изменить импорт (строка 14, было `from scheduler.broadcaster import schedule_chat_broadcast`):

```python
from scheduler.broadcaster import schedule_chat_broadcast
from scheduler.proactive import schedule_chat_proactive
```

Добавить в конец файла:

```python
_SETPROACTIVE_USAGE = (
    "Использование:\n"
    "/setproactive off — выключить\n"
    "/setproactive interval «минуты» — раз в N минут, если было новое сообщение\n"
    "/setproactive chance «процент 1-100» — шанс среагировать на каждое сообщение"
)


@router.message(Command("setproactive"))
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
```

В `admin/bot_commands.py` добавить в `BOT_COMMANDS` (после строки `BotCommand(command="setpersona", ...)`):

```python
    BotCommand(
        command="setproactive",
        description="Проактивные сообщения: off / interval «мин» / chance «%» (админ)",
    ),
    BotCommand(
        command="setproactivecontext",
        description="Сколько последних сообщений учитывать в проактивном ответе, 1-10 (админ)",
    ),
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_admin_commands.py tests/test_bot_commands.py -v`
Expected: PASS — все тесты обоих файлов.

- [ ] **Step 5: Commit**

```bash
git add admin/commands.py admin/bot_commands.py tests/test_admin_commands.py tests/test_bot_commands.py
git commit -m "$(cat <<'EOF'
Add /setproactive and /setproactivecontext admin commands

/setproactive off|interval N|chance P mirrors the existing
/setinterval validation style and keeps the scheduler job in sync:
switching to off or chance always re-runs schedule_chat_proactive with
0 to tear down any interval job left over from a previous mode.
/setproactivecontext controls how many recent messages (1-10) feed
into both trigger modes' AI call.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Полная проверка набора тестов

**Files:**
- Нет изменений кода — только верификация.

**Interfaces:**
- Не применимо.

- [ ] **Step 1: Прогнать весь набор тестов проекта**

Run: `pytest -v`
Expected: PASS — весь набор, включая все файлы, затронутые Task 1–6 (`test_proactive_buffer.py`, `test_repository.py`, `test_openrouter_client.py`, `test_scheduler_proactive.py`, `test_moderation_handlers.py`, `test_admin_commands.py`, `test_bot_commands.py`) и не затронутые (`test_ai_handlers.py`, `test_ai_tools.py`, `test_broadcaster.py`, `test_group_commands.py`, `test_moderation_actions.py`, `test_permissions.py`).

- [ ] **Step 2: Проверить, что список изменённых файлов соответствует плану**

Run: `git diff --stat <commit-до-Task-1>..HEAD`
Expected: только файлы, перечисленные в разделе «File Structure» этого плана (плюс `bot.py`), никаких лишних изменений.

- [ ] **Step 3: Ручная проверка (не тест, а чтение кода) — mutual exclusivity режимов**

Открыть `db/repository.py` и убедиться, что `set_proactive_interval`/`set_proactive_probability` действительно взаимно обнуляют друг друга (это уже покрыто тестами Task 2, здесь — финальная сверка перед тем как считать фичу done).

Никакого коммита в этой задаче не требуется — это верификационный чек-пойнт перед финальным ревью всей ветки.
