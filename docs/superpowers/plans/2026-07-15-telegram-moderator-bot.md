# Telegram-бот-модератор — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Рабочий Telegram-бот на aiogram 3.x, который модерирует групповой чат по триггер-словам (предупреждение → мьют 5 минут → кик) и периодически шлёт настраиваемые сообщения, с состоянием в SQLite.

**Architecture:** Слоистая структура: чистая логика (`moderation/logic.py`) без побочных эффектов и без aiogram — покрыта юнит-тестами; слой данных (`db/repository.py`) — тонкая асинхронная обёртка над SQLite; слой интеграции (`moderation/handlers.py`, `admin/commands.py`, `scheduler/broadcaster.py`) связывает логику и данные с aiogram Bot/Dispatcher и тестируется через моки Bot. `bot.py` — точка входа, связывающая всё вместе.

**Tech Stack:** Python 3.11+, aiogram 3.x, aiosqlite, APScheduler (`AsyncIOScheduler`), python-dotenv, pytest + pytest-asyncio.

## Global Constraints

- Токен бота передаётся только через переменную окружения `BOT_TOKEN` (файл `.env`, не коммитится в git).
- Бот запускается локально командой `python bot.py` (long polling), без Docker.
- Сообщение с триггер-словом **не удаляется** из чата.
- Кик за 3-е нарушение = `ban` + немедленный `unban` — пользователь может вернуться по инвайт-ссылке.
- Эскалация наказаний: 1-е нарушение → предупреждение, 2-е → мьют на 5 минут, 3-е → кик, после чего счётчик нарушений сбрасывается на 0.
- `reset_days = 0` в настройках чата означает «никогда не сбрасывать счётчик нарушений по времени» (не 0 дней ожидания).
- Список триггер-слов чата = объединение слов из файла `moderation/trigger_words.txt` и слов, добавленных админами через `/addword` (хранятся в SQLite).

---

### Task 1: Инициализация проекта и конфигурация

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: `conftest.py`
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.BOT_TOKEN: str`, `config.DB_PATH: str`, `config.TRIGGER_WORDS_FILE: str` — используются во всех последующих задачах, где нужен доступ к настройкам окружения.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_config.py`:

```python
import importlib

import pytest


def test_loads_bot_token_from_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BOT_TOKEN=test-token-123\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import config

    importlib.reload(config)

    assert config.BOT_TOKEN == "test-token-123"


def test_missing_bot_token_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import config

    with pytest.raises(KeyError):
        importlib.reload(config)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'` (файла ещё нет)

- [ ] **Step 3: Создать конфигурационные файлы**

`requirements.txt`:

```
aiogram>=3.4,<4
aiosqlite>=0.19,<1
python-dotenv>=1.0,<2
apscheduler>=3.10,<4
pytest>=8.0,<9
pytest-asyncio>=0.23,<1
```

`.env.example`:

```
BOT_TOKEN=your-telegram-bot-token-here
```

`.gitignore`:

```
.env
data/*.db
__pycache__/
*.pyc
.pytest_cache/
```

`pytest.ini`:

```
[pytest]
asyncio_mode = auto
```

`conftest.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
```

`config.py`:

```python
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TRIGGER_WORDS_FILE = os.environ.get("TRIGGER_WORDS_FILE", "moderation/trigger_words.txt")
```

- [ ] **Step 4: Установить зависимости и убедиться, что тест проходит**

Run: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && pytest tests/test_config.py -v`
Expected: PASS — оба теста зелёные

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example .gitignore pytest.ini conftest.py config.py tests/test_config.py
git commit -m "Add project scaffolding and env-based config"
```

---

### Task 2: Схема БД и слой доступа к данным

**Files:**
- Create: `db/__init__.py`
- Create: `db/models.sql`
- Create: `db/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: ничего (использует только `aiosqlite`)
- Produces: класс `Repository` с методами `create(db_path)`, `close()`, `get_chat_settings(chat_id)`, `set_broadcast_interval(chat_id, minutes)`, `set_reset_days(chat_id, days)`, `add_trigger_word(chat_id, word)`, `delete_trigger_word(chat_id, word)`, `list_trigger_words(chat_id)`, `get_warning(chat_id, user_id)`, `set_warning(chat_id, user_id, count, last_violation_at)`, `reset_warning(chat_id, user_id)`, `add_broadcast_message(chat_id, text)`, `delete_broadcast_message(chat_id, message_id)`, `list_broadcast_messages(chat_id)`, `list_active_broadcast_chats()` — используются во всех последующих задачах.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_repository.py`:

```python
import pytest

from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


async def test_chat_settings_defaults(repo):
    interval, reset_days = await repo.get_chat_settings(chat_id=1)
    assert interval == 0
    assert reset_days == 30


async def test_set_broadcast_interval(repo):
    await repo.set_broadcast_interval(chat_id=1, minutes=60)
    interval, _ = await repo.get_chat_settings(chat_id=1)
    assert interval == 60


async def test_set_reset_days(repo):
    await repo.set_reset_days(chat_id=1, days=7)
    _, reset_days = await repo.get_chat_settings(chat_id=1)
    assert reset_days == 7


async def test_trigger_words_add_list_delete(repo):
    await repo.add_trigger_word(chat_id=1, word="Спам")
    words = await repo.list_trigger_words(chat_id=1)
    assert words == ["спам"]

    deleted = await repo.delete_trigger_word(chat_id=1, word="спам")
    assert deleted is True
    assert await repo.list_trigger_words(chat_id=1) == []


async def test_delete_trigger_word_not_found(repo):
    deleted = await repo.delete_trigger_word(chat_id=1, word="нетслова")
    assert deleted is False


async def test_warning_lifecycle(repo):
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert (count, last_at) == (0, None)

    await repo.set_warning(chat_id=1, user_id=100, count=2, last_violation_at="2026-07-15T00:00:00")
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2
    assert last_at == "2026-07-15T00:00:00"

    await repo.reset_warning(chat_id=1, user_id=100)
    count, last_at = await repo.get_warning(chat_id=1, user_id=100)
    assert (count, last_at) == (0, None)


async def test_broadcast_messages(repo):
    msg_id = await repo.add_broadcast_message(chat_id=1, text="Hello")
    assert await repo.list_broadcast_messages(chat_id=1) == [(msg_id, "Hello")]

    deleted = await repo.delete_broadcast_message(chat_id=1, message_id=msg_id)
    assert deleted is True
    assert await repo.list_broadcast_messages(chat_id=1) == []


async def test_list_active_broadcast_chats(repo):
    await repo.set_broadcast_interval(chat_id=1, minutes=30)
    await repo.set_broadcast_interval(chat_id=2, minutes=0)
    active = await repo.list_active_broadcast_chats()
    assert active == [(1, 30)]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Написать схему и репозиторий**

Создать `db/__init__.py` (пустой файл).

`db/models.sql`:

```sql
CREATE TABLE IF NOT EXISTS trigger_words (
    chat_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    UNIQUE(chat_id, word)
);

CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_violation_at TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY,
    broadcast_interval_min INTEGER NOT NULL DEFAULT 0,
    reset_days INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS broadcast_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL
);
```

`db/repository.py`:

```python
from __future__ import annotations

import os
from typing import Optional

import aiosqlite

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "models.sql")


class Repository:
    def __init__(self, connection: aiosqlite.Connection):
        self._conn = connection

    @classmethod
    async def create(cls, db_path: str) -> "Repository":
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = await aiosqlite.connect(db_path)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            await conn.executescript(f.read())
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def get_chat_settings(self, chat_id: int) -> tuple[int, int]:
        await self._conn.execute(
            "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,)
        )
        await self._conn.commit()
        cursor = await self._conn.execute(
            "SELECT broadcast_interval_min, reset_days FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1])

    async def set_broadcast_interval(self, chat_id: int, minutes: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET broadcast_interval_min = ? WHERE chat_id = ?",
            (minutes, chat_id),
        )
        await self._conn.commit()

    async def set_reset_days(self, chat_id: int, days: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET reset_days = ? WHERE chat_id = ?",
            (days, chat_id),
        )
        await self._conn.commit()

    async def add_trigger_word(self, chat_id: int, word: str) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO trigger_words (chat_id, word) VALUES (?, ?)",
            (chat_id, word.lower()),
        )
        await self._conn.commit()

    async def delete_trigger_word(self, chat_id: int, word: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM trigger_words WHERE chat_id = ? AND word = ?",
            (chat_id, word.lower()),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_trigger_words(self, chat_id: int) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT word FROM trigger_words WHERE chat_id = ?", (chat_id,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_warning(self, chat_id: int, user_id: int) -> tuple[int, Optional[str]]:
        cursor = await self._conn.execute(
            "SELECT count, last_violation_at FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return (0, None)
        return (row[0], row[1])

    async def set_warning(
        self, chat_id: int, user_id: int, count: int, last_violation_at: str
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO warnings (chat_id, user_id, count, last_violation_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                count = excluded.count,
                last_violation_at = excluded.last_violation_at
            """,
            (chat_id, user_id, count, last_violation_at),
        )
        await self._conn.commit()

    async def reset_warning(self, chat_id: int, user_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self._conn.commit()

    async def add_broadcast_message(self, chat_id: int, text: str) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO broadcast_messages (chat_id, text) VALUES (?, ?)",
            (chat_id, text),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def delete_broadcast_message(self, chat_id: int, message_id: int) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM broadcast_messages WHERE chat_id = ? AND id = ?",
            (chat_id, message_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_broadcast_messages(self, chat_id: int) -> list[tuple[int, str]]:
        cursor = await self._conn.execute(
            "SELECT id, text FROM broadcast_messages WHERE chat_id = ?", (chat_id,)
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def list_active_broadcast_chats(self) -> list[tuple[int, int]]:
        cursor = await self._conn.execute(
            "SELECT chat_id, broadcast_interval_min FROM chat_settings "
            "WHERE broadcast_interval_min > 0"
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_repository.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add db/ tests/test_repository.py
git commit -m "Add SQLite schema and async repository layer"
```

---

### Task 3: Чистая логика модерации

**Files:**
- Create: `moderation/__init__.py`
- Create: `moderation/trigger_words.txt`
- Create: `moderation/logic.py`
- Test: `tests/test_logic.py`

**Interfaces:**
- Consumes: ничего (чистые функции, без внешних зависимостей)
- Produces: `load_trigger_words_from_file(path) -> list[str]`, `merge_trigger_words(file_words, db_words) -> list[str]`, `contains_trigger_word(text, trigger_words) -> bool`, `compute_violation(current_count, last_violation_at, reset_days, now) -> tuple[int, str]` — используются в `moderation/handlers.py` (Task 5).

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_logic.py`:

```python
from datetime import datetime, timedelta

from moderation.logic import (
    compute_violation,
    contains_trigger_word,
    merge_trigger_words,
)


def test_contains_trigger_word_case_insensitive():
    assert contains_trigger_word("Это СПАМ сообщение", ["спам"]) is True


def test_contains_trigger_word_no_match():
    assert contains_trigger_word("Обычное сообщение", ["спам"]) is False


def test_contains_trigger_word_empty_list():
    assert contains_trigger_word("что угодно", []) is False


def test_merge_trigger_words_deduplicates():
    result = merge_trigger_words(["спам", "реклама"], ["РЕКЛАМА", "оскорбление"])
    assert result == sorted({"спам", "реклама", "оскорбление"})


def test_compute_violation_first_is_warn():
    count, punishment = compute_violation(0, None, reset_days=30, now=datetime(2026, 1, 1))
    assert (count, punishment) == (1, "warn")


def test_compute_violation_second_is_mute():
    count, punishment = compute_violation(
        1, datetime(2026, 1, 1), reset_days=30, now=datetime(2026, 1, 1, 1)
    )
    assert (count, punishment) == (2, "mute")


def test_compute_violation_third_is_kick_and_resets():
    count, punishment = compute_violation(
        2, datetime(2026, 1, 1), reset_days=30, now=datetime(2026, 1, 1, 1)
    )
    assert (count, punishment) == (0, "kick")


def test_compute_violation_resets_after_window_expires():
    old_violation = datetime(2026, 1, 1)
    now = old_violation + timedelta(days=31)
    count, punishment = compute_violation(2, old_violation, reset_days=30, now=now)
    assert (count, punishment) == (1, "warn")


def test_compute_violation_never_resets_when_reset_days_zero():
    old_violation = datetime(2020, 1, 1)
    now = datetime(2026, 1, 1)
    count, punishment = compute_violation(1, old_violation, reset_days=0, now=now)
    assert (count, punishment) == (2, "mute")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moderation'`

- [ ] **Step 3: Написать реализацию**

Создать `moderation/__init__.py` (пустой файл).

`moderation/trigger_words.txt`:

```
# Список слов-триггеров модерации, по одному на строку.
# Строки, начинающиеся с #, и пустые строки игнорируются.
# Добавляйте сюда слова вручную, либо командой /addword прямо в чате.
```

`moderation/logic.py`:

```python
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
    return sorted(set(file_words) | set(db_words))


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
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_logic.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add moderation/__init__.py moderation/trigger_words.txt moderation/logic.py tests/test_logic.py
git commit -m "Add pure moderation logic: trigger matching and punishment escalation"
```

---

### Task 4: Проверка прав администратора

**Files:**
- Create: `admin/__init__.py`
- Create: `admin/permissions.py`
- Test: `tests/test_permissions.py`

**Interfaces:**
- Consumes: `aiogram.Bot` (метод `get_chat_member`)
- Produces: `is_admin(bot, chat_id, user_id) -> bool` — используется в Task 5 (пропуск модерации для админов) и Task 6 (проверка прав на админ-команды).

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_permissions.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

from admin.permissions import is_admin


async def test_is_admin_true_for_administrator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is True
    bot.get_chat_member.assert_awaited_once_with(1, 100)


async def test_is_admin_true_for_creator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="creator")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is True


async def test_is_admin_false_for_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="member")

    result = await is_admin(bot, chat_id=1, user_id=100)

    assert result is False
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'admin'`

- [ ] **Step 3: Написать реализацию**

Создать `admin/__init__.py` (пустой файл).

`admin/permissions.py`:

```python
from __future__ import annotations

from aiogram import Bot

ADMIN_STATUSES = {"administrator", "creator"}


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ADMIN_STATUSES
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_permissions.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add admin/__init__.py admin/permissions.py tests/test_permissions.py
git commit -m "Add admin permission check helper"
```

---

### Task 5: Обработчик модерации сообщений

**Files:**
- Create: `moderation/handlers.py`
- Test: `tests/test_moderation_handlers.py`

**Interfaces:**
- Consumes: `Repository` (Task 2), `is_admin` (Task 4), `contains_trigger_word`/`merge_trigger_words`/`compute_violation` (Task 3)
- Produces: `handle_moderated_message(message, bot, repository, default_trigger_words)`, `router` (aiogram `Router`, name `"moderation"`) — `router` подключается в `bot.py` (Task 8).

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_moderation_handlers.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db.repository import Repository
from moderation.handlers import handle_moderated_message


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


def make_message(text, user_id=100, chat_id=1):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(
        text=text,
        from_user=from_user,
        chat=SimpleNamespace(id=chat_id),
        answer=AsyncMock(),
    )


async def make_bot(admin_ids=()):
    bot = AsyncMock()

    async def get_chat_member(chat_id, user_id):
        status = "administrator" if user_id in admin_ids else "member"
        return SimpleNamespace(status=status)

    bot.get_chat_member.side_effect = get_chat_member
    return bot


async def test_admin_messages_are_ignored(repo):
    bot = await make_bot(admin_ids={100})
    message = make_message("это спам сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_not_called()
    bot.restrict_chat_member.assert_not_called()


async def test_non_trigger_message_ignored(repo):
    bot = await make_bot()
    message = make_message("обычное сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_not_called()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 0


async def test_first_violation_sends_warning(repo):
    bot = await make_bot()
    message = make_message("это спам сообщение")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once()
    bot.restrict_chat_member.assert_not_called()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 1


async def test_second_violation_mutes(repo):
    bot = await make_bot()
    message = make_message("спам")

    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    bot.restrict_chat_member.assert_awaited_once()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 2


async def test_third_violation_kicks_and_resets(repo):
    bot = await make_bot()
    message = make_message("спам")

    for _ in range(3):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    bot.ban_chat_member.assert_awaited_once()
    bot.unban_chat_member.assert_awaited_once()
    count, _ = await repo.get_warning(chat_id=1, user_id=100)
    assert count == 0


@pytest.fixture(autouse=True)
def clear_permission_notice_cache():
    import moderation.handlers as handlers_module

    handlers_module._last_permission_notice.clear()
    yield
    handlers_module._last_permission_notice.clear()


async def test_missing_bot_permissions_notifies_once_and_throttles(repo):
    from datetime import datetime, timezone

    from aiogram.exceptions import TelegramAPIError

    now_iso = datetime.now(timezone.utc).isoformat()
    await repo.set_warning(chat_id=1, user_id=100, count=1, last_violation_at=now_iso)
    await repo.set_warning(chat_id=1, user_id=200, count=1, last_violation_at=now_iso)

    bot = await make_bot()
    bot.restrict_chat_member.side_effect = TelegramAPIError(method=None, message="Not enough rights")

    message1 = make_message("спам", user_id=100)
    message2 = make_message("спам", user_id=200)

    await handle_moderated_message(message1, bot, repo, default_trigger_words=["спам"])
    await handle_moderated_message(message2, bot, repo, default_trigger_words=["спам"])

    assert message1.answer.await_count == 1
    assert "прав администратора" in message1.answer.await_args.args[0]
    assert message2.answer.await_count == 0
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_moderation_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moderation.handlers'`

- [ ] **Step 3: Написать реализацию**

`moderation/handlers.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message

from admin.permissions import is_admin
from db.repository import Repository
from moderation.logic import compute_violation, contains_trigger_word, merge_trigger_words

router = Router(name="moderation")

MUTE_MINUTES = 5

WARN_TEMPLATES = {
    "warn": "{mention}, предупреждение: сообщение нарушает правила чата.",
    "mute": "{mention} получает ограничение на отправку сообщений на {minutes} минут "
    "за повторное нарушение.",
    "kick": "{mention} удаляется из чата за повторные нарушения. "
    "Вернуться можно по новой ссылке-приглашению.",
}

PERMISSION_NOTICE_COOLDOWN = timedelta(minutes=10)
_last_permission_notice: dict[int, datetime] = {}


def _mention(message: Message) -> str:
    return message.from_user.mention_html()


async def _notify_missing_permissions(message: Message) -> None:
    now = datetime.now(timezone.utc)
    last_notice = _last_permission_notice.get(message.chat.id)
    if last_notice is not None and now - last_notice < PERMISSION_NOTICE_COOLDOWN:
        return
    _last_permission_notice[message.chat.id] = now
    await message.answer(
        "Боту не хватает прав администратора, чтобы ограничивать/удалять участников."
    )


async def handle_moderated_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    if message.from_user is None or message.text is None:
        return

    if await is_admin(bot, message.chat.id, message.from_user.id):
        return

    db_words = await repository.list_trigger_words(message.chat.id)
    trigger_words = merge_trigger_words(default_trigger_words, db_words)

    if not contains_trigger_word(message.text, trigger_words):
        return

    count, last_violation_at_raw = await repository.get_warning(
        message.chat.id, message.from_user.id
    )
    _, reset_days = await repository.get_chat_settings(message.chat.id)

    last_violation_at = (
        datetime.fromisoformat(last_violation_at_raw) if last_violation_at_raw else None
    )
    now = datetime.now(timezone.utc)

    new_count, punishment = compute_violation(count, last_violation_at, reset_days, now)
    await repository.set_warning(
        message.chat.id, message.from_user.id, new_count, now.isoformat()
    )

    if punishment == "mute":
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=now + timedelta(minutes=MUTE_MINUTES),
            )
        except TelegramAPIError:
            await _notify_missing_permissions(message)
            return
    elif punishment == "kick":
        try:
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            await bot.unban_chat_member(message.chat.id, message.from_user.id, only_if_banned=True)
        except TelegramAPIError:
            await _notify_missing_permissions(message)
            return

    text = WARN_TEMPLATES[punishment].format(mention=_mention(message), minutes=MUTE_MINUTES)
    await message.answer(text)


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def on_group_message(
    message: Message,
    bot: Bot,
    repository: Repository,
    default_trigger_words: list[str],
) -> None:
    await handle_moderated_message(message, bot, repository, default_trigger_words)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_moderation_handlers.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add moderation/handlers.py tests/test_moderation_handlers.py
git commit -m "Add moderation message handler with punishment escalation"
```

---

### Task 6: Админ-команды (слова, предупреждения, настройки)

**Files:**
- Create: `admin/commands.py`
- Test: `tests/test_admin_commands.py`

**Interfaces:**
- Consumes: `Repository` (Task 2), `is_admin` (Task 4)
- Produces: `router` (aiogram `Router`, name `"admin"`) с командами `cmd_addword`, `cmd_delword`, `cmd_listwords`, `cmd_warns`, `cmd_resetwarns`, `cmd_setresetdays`, `cmd_setinterval`, `cmd_addmsg`, `cmd_delmsg`, `cmd_listmsgs` — `router` подключается в `bot.py` (Task 8); `cmd_setinterval` дорабатывается в Task 7 (добавляется параметр `scheduler`).

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_admin_commands.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import CommandObject

from admin import commands
from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


def make_message(user_id=1, chat_id=1, reply_to=None):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=from_user,
        reply_to_message=reply_to,
        answer=AsyncMock(),
    )


def make_reply_user(user_id):
    from_user = SimpleNamespace(id=user_id, mention_html=lambda: f"User{user_id}")
    return SimpleNamespace(from_user=from_user)


async def make_bot(is_admin_user_id=1):
    bot = AsyncMock()

    async def get_chat_member(chat_id, user_id):
        status = "administrator" if user_id == is_admin_user_id else "member"
        return SimpleNamespace(status=status)

    bot.get_chat_member.side_effect = get_chat_member
    return bot


def cmd(args):
    return CommandObject(prefix="/", command="x", args=args)


async def test_addword_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd("спам"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    assert await repo.list_trigger_words(1) == []


async def test_addword_adds_word(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd("спам"), bot, repo)

    assert await repo.list_trigger_words(1) == ["спам"]


async def test_addword_without_args(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addword(message, cmd(None), bot, repo)

    message.answer.assert_awaited_once_with("Использование: /addword <слово>")


async def test_delword_removes_existing(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.add_trigger_word(1, "спам")
    message = make_message(user_id=1)

    await commands.cmd_delword(message, cmd("спам"), bot, repo)

    assert await repo.list_trigger_words(1) == []


async def test_listwords_empty(repo):
    message = make_message(user_id=1)

    await commands.cmd_listwords(message, repo)

    message.answer.assert_awaited_once_with("Дополнительных триггер-слов для этого чата нет.")


async def test_warns_reports_count(repo):
    await repo.set_warning(chat_id=1, user_id=42, count=2, last_violation_at="2026-07-15T00:00:00")
    message = make_message(user_id=1, reply_to=make_reply_user(42))

    await commands.cmd_warns(message, repo)

    message.answer.assert_awaited_once()
    assert "2" in message.answer.await_args.args[0]


async def test_resetwarns_clears_count(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_warning(chat_id=1, user_id=42, count=2, last_violation_at="2026-07-15T00:00:00")
    message = make_message(user_id=1, reply_to=make_reply_user(42))

    await commands.cmd_resetwarns(message, bot, repo)

    count, _ = await repo.get_warning(1, 42)
    assert count == 0


async def test_setresetdays_rejects_non_numeric(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setresetdays(message, cmd("много"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Использование: /setresetdays <число дней, 0 = никогда>"
    )


async def test_setresetdays_updates_value(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setresetdays(message, cmd("7"), bot, repo)

    _, reset_days = await repo.get_chat_settings(1)
    assert reset_days == 7


async def test_addmsg_and_listmsgs(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_addmsg(message, cmd("Привет всем!"), bot, repo)
    await commands.cmd_listmsgs(message, repo)

    stored = await repo.list_broadcast_messages(1)
    assert stored[0][1] == "Привет всем!"


async def test_delmsg_removes_message(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)
    msg_id = await repo.add_broadcast_message(1, "Текст")

    await commands.cmd_delmsg(message, cmd(str(msg_id)), bot, repo)

    assert await repo.list_broadcast_messages(1) == []
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_admin_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'admin.commands'`

- [ ] **Step 3: Написать реализацию**

`admin/commands.py`:

```python
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
    if not command.args:
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
async def cmd_listmsgs(message: Message, repository: Repository) -> None:
    messages = await repository.list_broadcast_messages(message.chat.id)
    if not messages:
        await message.answer("Пул сообщений рассылки пуст.")
        return
    lines = [f"{msg_id}: {text}" for msg_id, text in messages]
    await message.answer("Сообщения рассылки:\n" + "\n".join(lines))
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_admin_commands.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add admin/commands.py tests/test_admin_commands.py
git commit -m "Add admin commands for trigger words, warnings, and broadcast settings"
```

---

### Task 7: Планировщик периодической рассылки

**Files:**
- Create: `scheduler/__init__.py`
- Create: `scheduler/broadcaster.py`
- Modify: `admin/commands.py` (функция `cmd_setinterval`)
- Modify: `tests/test_admin_commands.py` (тесты `cmd_setinterval`)
- Test: `tests/test_broadcaster.py`

**Interfaces:**
- Consumes: `Repository` (Task 2), `apscheduler.schedulers.asyncio.AsyncIOScheduler`
- Produces: `send_broadcast(bot, repository, chat_id)`, `schedule_chat_broadcast(scheduler, bot, repository, chat_id, interval_minutes)`, `load_scheduled_broadcasts(scheduler, bot, repository)` — используются в `bot.py` (Task 8) и в `cmd_setinterval`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_broadcaster.py`:

```python
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import Repository
from scheduler.broadcaster import (
    load_scheduled_broadcasts,
    schedule_chat_broadcast,
    send_broadcast,
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


async def test_send_broadcast_picks_message(repo):
    bot = AsyncMock()
    await repo.add_broadcast_message(chat_id=1, text="Привет!")

    await send_broadcast(bot, repo, chat_id=1)

    bot.send_message.assert_awaited_once_with(1, "Привет!")


async def test_send_broadcast_skips_when_pool_empty(repo):
    bot = AsyncMock()

    await send_broadcast(bot, repo, chat_id=1)

    bot.send_message.assert_not_called()


async def test_schedule_chat_broadcast_registers_job(repo, scheduler):
    bot = AsyncMock()

    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    assert scheduler.get_job("broadcast_1") is not None


async def test_schedule_chat_broadcast_removes_job_when_zero(repo, scheduler):
    bot = AsyncMock()
    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=0)

    assert scheduler.get_job("broadcast_1") is None


async def test_load_scheduled_broadcasts_registers_active_chats(repo, scheduler):
    bot = AsyncMock()
    await repo.set_broadcast_interval(chat_id=1, minutes=45)
    await repo.set_broadcast_interval(chat_id=2, minutes=0)

    await load_scheduled_broadcasts(scheduler, bot, repo)

    assert scheduler.get_job("broadcast_1") is not None
    assert scheduler.get_job("broadcast_2") is None


async def test_scheduled_broadcast_job_removes_job_on_api_error(repo, scheduler):
    from aiogram.exceptions import TelegramAPIError

    from scheduler.broadcaster import _scheduled_broadcast_job

    bot = AsyncMock()
    bot.send_message.side_effect = TelegramAPIError(method=None, message="bot was kicked")
    await repo.add_broadcast_message(chat_id=1, text="Привет!")
    schedule_chat_broadcast(scheduler, bot, repo, chat_id=1, interval_minutes=30)

    await _scheduled_broadcast_job(scheduler, bot, repo, chat_id=1)

    assert scheduler.get_job("broadcast_1") is None
```

Также обновить в `tests/test_admin_commands.py` тест `test_setinterval_updates_value`, добавив параметр `scheduler` (сигнатура `cmd_setinterval` меняется в Step 3):

```python
async def test_setinterval_updates_value(repo, scheduler):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setinterval(message, cmd("15"), bot, repo, scheduler)

    interval, _ = await repo.get_chat_settings(1)
    assert interval == 15
    assert scheduler.get_job("broadcast_1") is not None
```

Добавить фикстуру `scheduler` в `tests/test_admin_commands.py` (рядом с фикстурой `repo`):

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler


@pytest.fixture
def scheduler():
    sched = AsyncIOScheduler()
    yield sched
    if sched.running:
        sched.shutdown(wait=False)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_broadcaster.py tests/test_admin_commands.py -v`
Expected: FAIL — `tests/test_broadcaster.py` не находит модуль `scheduler.broadcaster`; `test_setinterval_updates_value` падает с `TypeError` (лишний аргумент `scheduler`)

- [ ] **Step 3: Написать реализацию**

Создать `scheduler/__init__.py` (пустой файл).

`scheduler/broadcaster.py`:

```python
from __future__ import annotations

import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import Repository


def _job_id(chat_id: int) -> str:
    return f"broadcast_{chat_id}"


async def send_broadcast(bot: Bot, repository: Repository, chat_id: int) -> None:
    messages = await repository.list_broadcast_messages(chat_id)
    if not messages:
        return
    _, text = random.choice(messages)
    await bot.send_message(chat_id, text)


async def _scheduled_broadcast_job(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository, chat_id: int
) -> None:
    try:
        await send_broadcast(bot, repository, chat_id)
    except TelegramAPIError:
        job_id = _job_id(chat_id)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)


def schedule_chat_broadcast(
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
        _scheduled_broadcast_job,
        "interval",
        minutes=interval_minutes,
        id=job_id,
        args=[scheduler, bot, repository, chat_id],
        replace_existing=True,
    )


async def load_scheduled_broadcasts(
    scheduler: AsyncIOScheduler, bot: Bot, repository: Repository
) -> None:
    for chat_id, interval_minutes in await repository.list_active_broadcast_chats():
        schedule_chat_broadcast(scheduler, bot, repository, chat_id, interval_minutes)
```

В `admin/commands.py` заменить импорт и функцию `cmd_setinterval`:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scheduler.broadcaster import schedule_chat_broadcast
```

```python
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
        await message.answer("Использование: /setinterval <минуты, 0 = выключить>")
        return
    minutes = int(command.args.strip())
    await repository.set_broadcast_interval(message.chat.id, minutes)
    schedule_chat_broadcast(scheduler, bot, repository, message.chat.id, minutes)
    await message.answer(f"Интервал рассылки установлен: {minutes} мин. (0 = выключено).")
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `pytest tests/test_broadcaster.py tests/test_admin_commands.py -v`
Expected: PASS — все тесты зелёные

- [ ] **Step 5: Commit**

```bash
git add scheduler/ admin/commands.py tests/test_broadcaster.py tests/test_admin_commands.py
git commit -m "Add broadcast scheduler and wire it into /setinterval"
```

---

### Task 8: Точка входа и связывание бота

**Files:**
- Create: `bot.py`

**Interfaces:**
- Consumes: `config` (Task 1), `Repository` (Task 2), `load_trigger_words_from_file` (Task 3), `moderation.handlers.router` (Task 5), `admin.commands.router` (Task 6), `load_scheduled_broadcasts` (Task 7)
- Produces: `main()` — запускает бота, ничего не потребляется другими задачами (конечная точка сборки)

- [ ] **Step 1: Написать `bot.py`**

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from admin.commands import router as admin_router
from db.repository import Repository
from moderation.handlers import router as moderation_router
from moderation.logic import load_trigger_words_from_file
from scheduler.broadcaster import load_scheduled_broadcasts

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(moderation_router)

    repository = await Repository.create(config.DB_PATH)
    default_trigger_words = load_trigger_words_from_file(config.TRIGGER_WORDS_FILE)
    scheduler = AsyncIOScheduler()
    await load_scheduled_broadcasts(scheduler, bot, repository)
    scheduler.start()

    try:
        await dp.start_polling(
            bot,
            repository=repository,
            default_trigger_words=default_trigger_words,
            scheduler=scheduler,
        )
    finally:
        scheduler.shutdown(wait=False)
        await repository.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Обратите внимание на порядок `dp.include_router(...)`: сначала `admin_router` (иначе команды типа `/addword` попадут в общий текстовый обработчик модерации раньше, чем до них дойдёт роутер команд), затем `moderation_router`.

- [ ] **Step 2: Проверить, что модуль импортируется без ошибок**

Run: `BOT_TOKEN=dummy python3 -c "import bot"`
Expected: без ошибок импорта (никаких вызовов Telegram API при простом импорте не происходит)

- [ ] **Step 3: Прогнать весь набор автотестов**

Run: `pytest -v`
Expected: PASS — все тесты из Task 1–7 зелёные

- [ ] **Step 4: Ручная проверка в реальном Telegram (нельзя автоматизировать)**

1. Заполнить `.env` из `.env.example`, вставив реальный `BOT_TOKEN` (полученный от @BotFather).
2. Создать тестовую группу в Telegram, добавить бота, выдать ему права администратора (минимум: «Блокировка участников», «Удаление сообщений» не требуется, т.к. сообщения не удаляются).
3. Запустить бота: `source venv/bin/activate && python bot.py`.
4. В группе от имени администратора выполнить `/addword тестслово`, затем `/listwords` — убедиться, что слово появилось.
5. От имени **другого**, не-админского аккаунта трижды подряд написать сообщение с этим словом — проверить: 1-е — ответ-предупреждение, 2-е — сообщение об ограничении и невозможность писать 5 минут, 3-е — сообщение о киках и что участник исчез из списка участников.
6. Выполнить `/addmsg Привет из теста` и `/setinterval 1` — убедиться, что раз в минуту в чат приходит это сообщение.
7. Выполнить `/setinterval 0` — убедиться, что рассылка прекратилась.
8. Остановить бота (Ctrl+C), перезапустить `python bot.py`, выполнить `/listwords` — убедиться, что слово из шага 4 сохранилось (проверка персистентности SQLite).

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "Add bot entrypoint wiring moderation, admin commands, and scheduler"
```

---

## Итоговая проверка перед использованием

- `pytest -v` — все автотесты проходят.
- Ручной сценарий из Task 8 Step 4 пройден в реальной тестовой группе.
- `.env` с реальным токеном не закоммичен (проверить `git status`).
