# Настраиваемая «личность» бота на чат (/setpersona) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-chat free-text "persona" instruction, settable via `/setpersona`, that shapes both `/ask` answers and (when set) AI-generated reactions to trigger-word violations, replacing the static punishment template only when the AI call succeeds.

**Architecture:** One nullable `persona` column on `chat_settings` (same migration pattern as `warn_message`). `/ask`'s system prompt gets the persona appended as an extra block after the existing `SYSTEM_PROMPT`. A new `generate_violation_reaction()` in `ai/openrouter_client.py` does a single non-tool OpenRouter completion call and swallows all errors into `None`; `moderation/handlers.py` calls it only when a persona is set, and falls back to the existing static-template path on `None`. Escalation logic (warn/mute/kick) is untouched — persona only changes message text.

**Tech Stack:** Python 3.14, aiogram 3, aiosqlite, aiohttp, pytest + pytest-asyncio (`asyncio_mode = auto`, see `pytest.ini`).

## Global Constraints

- Persona text max length: **500 characters** (enforced in the command handler, not in the DB layer).
- `generate_violation_reaction` HTTP timeout: **10 seconds** (`aiohttp.ClientTimeout(total=10)`).
- Persona is appended **after** `SYSTEM_PROMPT`, never replacing it.
- Trigger-word reaction only calls the AI when a persona is configured for the chat; no persona → zero behavior change (no AI call, existing templates as-is).
- Any failure from `generate_violation_reaction` (missing API key, non-200, timeout, network error, empty/malformed response) must return `None`, never raise — the caller has no try/except around it.
- All chat-facing text sent under default `parse_mode="HTML"` must be `html.escape()`d before sending (per existing convention from commit `31a2ef8`).
- Run tests with: `python -m pytest <path> -v` (repo root, `pytest.ini` sets `asyncio_mode = auto` so no `@pytest.mark.asyncio` needed).

---

### Task 1: Repository — persona storage

**Files:**
- Modify: `db/repository.py:11-19` (`_MIGRATION_COLUMNS`), and end of `Repository` class (after `set_kick_after`, currently ending at line 256)
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: nothing new (uses existing `self._conn`, `self.get_chat_settings`)
- Produces: `Repository.get_persona(chat_id: int) -> Optional[str]`, `Repository.set_persona(chat_id: int, text: Optional[str]) -> None` — used by Task 2 (command handler), Task 3 (`/ask` system prompt), Task 5 (moderation handler)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_repository.py` (after `test_set_kick_after`, end of file):

```python
async def test_persona_defaults_to_none(repo):
    assert await repo.get_persona(chat_id=1) is None


async def test_persona_set_and_get(repo):
    await repo.set_persona(chat_id=1, text="Отвечай дерзко и с юмором.")
    assert await repo.get_persona(chat_id=1) == "Отвечай дерзко и с юмором."


async def test_persona_cleared_with_none(repo):
    await repo.set_persona(chat_id=1, text="Дерзко")
    await repo.set_persona(chat_id=1, text=None)
    assert await repo.get_persona(chat_id=1) is None
```

Also update the existing migration test in the same file — add one line right before the final `await reopened_repo.close()`:

```python
async def test_migration_adds_columns_to_preexisting_db(tmp_path):
    db_path = str(tmp_path / "legacy.db")

    legacy_repo = await Repository.create(db_path)
    await legacy_repo.set_broadcast_interval(chat_id=1, minutes=10)
    await legacy_repo.close()

    reopened_repo = await Repository.create(db_path)
    templates = await reopened_repo.get_message_templates(chat_id=1)
    assert templates == (None, None, None)
    interval, _ = await reopened_repo.get_chat_settings(chat_id=1)
    assert interval == 10
    mute_minutes, kick_after = await reopened_repo.get_escalation_settings(chat_id=1)
    assert (mute_minutes, kick_after) == (5, 3)
    assert await reopened_repo.get_persona(chat_id=1) is None
    await reopened_repo.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repository.py -v -k persona`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'get_persona'`

- [ ] **Step 3: Implement the minimal code**

In `db/repository.py`, add `"persona": "TEXT"` to `_MIGRATION_COLUMNS`:

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
}
```

At the end of the `Repository` class, after `set_kick_after` (currently the last method, ending at line 255-256), add:

```python

    async def get_persona(self, chat_id: int) -> Optional[str]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT persona FROM chat_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def set_persona(self, chat_id: int, text: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET persona = ? WHERE chat_id = ?", (text, chat_id)
        )
        await self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_repository.py -v`
Expected: PASS (all tests in the file, including the updated migration test)

- [ ] **Step 5: Commit**

```bash
git add db/repository.py tests/test_repository.py
git commit -m "Add per-chat persona storage to Repository"
```

---

### Task 2: `/setpersona` admin command

**Files:**
- Modify: `admin/commands.py` (add at end of file)
- Modify: `admin/bot_commands.py:6-34` (`BOT_COMMANDS`)
- Test: `tests/test_admin_commands.py`, `tests/test_bot_commands.py`

**Interfaces:**
- Consumes: `Repository.get_persona`, `Repository.set_persona` (Task 1)
- Produces: `admin.commands.cmd_setpersona` — no other task depends on this directly, it's an entry point

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_commands.py` (end of file):

```python
async def test_setpersona_requires_admin(repo):
    bot = await make_bot(is_admin_user_id=999)
    message = make_message(user_id=1)

    await commands.cmd_setpersona(message, cmd("Дерзкий стиль"), bot, repo)

    message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам чата."
    )
    assert await repo.get_persona(1) is None


async def test_setpersona_sets_text(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setpersona(message, cmd("Отвечай дерзко и с юмором."), bot, repo)

    assert await repo.get_persona(1) == "Отвечай дерзко и с юмором."
    message.answer.assert_awaited_once_with("Инструкция поведения сохранена.")


async def test_setpersona_without_args_clears(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_persona(1, "старый стиль")
    message = make_message(user_id=1)

    await commands.cmd_setpersona(message, cmd(None), bot, repo)

    assert await repo.get_persona(1) is None
    message.answer.assert_awaited_once_with(
        "Инструкция поведения сброшена, бот вернулся к обычному стилю."
    )


async def test_setpersona_whitespace_only_clears(repo):
    bot = await make_bot(is_admin_user_id=1)
    await repo.set_persona(1, "старый стиль")
    message = make_message(user_id=1)

    await commands.cmd_setpersona(message, cmd("   "), bot, repo)

    assert await repo.get_persona(1) is None


async def test_setpersona_rejects_too_long(repo):
    bot = await make_bot(is_admin_user_id=1)
    message = make_message(user_id=1)

    await commands.cmd_setpersona(message, cmd("а" * 501), bot, repo)

    message.answer.assert_awaited_once_with("Слишком длинно — уложись в 500 символов.")
    assert await repo.get_persona(1) is None
```

Update `tests/test_bot_commands.py::test_bot_commands_cover_all_commands` — add `"setpersona"` to the expected set:

```python
def test_bot_commands_cover_all_commands():
    names = {command.command for command in BOT_COMMANDS}
    assert names == {
        "addword",
        "delword",
        "listwords",
        "warns",
        "resetwarns",
        "setresetdays",
        "setinterval",
        "addmsg",
        "delmsg",
        "listmsgs",
        "setwarnmsg",
        "setmutemsg",
        "setkickmsg",
        "resetmsgs",
        "ask",
        "setmuteminutes",
        "setkickafter",
        "setpersona",
        "pin",
        "unpin",
        "lock",
        "unlock",
        "newlink",
        "revokelink",
        "chatinfo",
        "settitle",
        "setdescription",
        "setphoto",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_commands.py tests/test_bot_commands.py -v -k "setpersona or cover_all_commands"`
Expected: FAIL — `AttributeError: module 'admin.commands' has no attribute 'cmd_setpersona'` and a set-mismatch `AssertionError` for the bot-commands test.

- [ ] **Step 3: Implement the minimal code**

In `admin/commands.py`, add at the end of the file:

```python


@router.message(Command("setpersona"))
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
    if len(text) > 500:
        await message.answer("Слишком длинно — уложись в 500 символов.")
        return
    await repository.set_persona(message.chat.id, text)
    await message.answer("Инструкция поведения сохранена.")
```

In `admin/bot_commands.py`, add to `BOT_COMMANDS` (after the `setkickafter` entry):

```python
    BotCommand(command="setpersona", description="Задать характер/стиль поведения бота, без текста — сбросить (админ)"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_commands.py tests/test_bot_commands.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add admin/commands.py admin/bot_commands.py tests/test_admin_commands.py tests/test_bot_commands.py
git commit -m "Add /setpersona admin command"
```

---

### Task 3: Persona in `/ask` system prompt

**Files:**
- Modify: `ai/openrouter_client.py` (inside `ask_ai_with_tools`, currently lines 224-227)
- Test: `tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: `Repository.get_persona(chat_id)` (Task 1) — `ask_ai_with_tools` already receives `repository` and `chat_id` as keyword args, no signature change
- Produces: no new public symbols; `ask_ai_with_tools` behavior extended (system message content now depends on persona)

- [ ] **Step 1: Write the failing tests**

In `tests/test_openrouter_client.py`, update the `_fake_repository` helper to accept and wire up a `persona` param (needed because the code under test will now unconditionally call `repository.get_persona`, and a bare `MagicMock()` attribute is not awaitable):

```python
def _fake_repository(
    broadcast_interval=0,
    reset_days=0,
    templates=(None, None, None),
    escalation=(5, 3),
    persona=None,
):
    repository = MagicMock()
    repository.get_chat_settings = AsyncMock(return_value=(broadcast_interval, reset_days))
    repository.get_message_templates = AsyncMock(return_value=templates)
    repository.get_escalation_settings = AsyncMock(return_value=escalation)
    repository.get_persona = AsyncMock(return_value=persona)
    return repository
```

Add new tests (near `test_ask_ai_with_tools_sends_only_meta_tools_in_payload`):

```python
async def test_ask_ai_with_tools_appends_persona_to_system_prompt(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = _text_response("ok")

    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        await ask_ai_with_tools(
            "Привет",
            tools=[],
            repository=_fake_repository(persona="Отвечай дерзко и с юмором."),
            chat_id=1,
        )

    payload = session.post.call_args.kwargs["json"]
    system_message = payload["messages"][0]
    assert system_message["role"] == "system"
    assert SYSTEM_PROMPT in system_message["content"]
    assert "Отвечай дерзко и с юмором." in system_message["content"]


async def test_ask_ai_with_tools_omits_persona_block_when_not_set(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = _text_response("ok")

    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        await ask_ai_with_tools(
            "Привет", tools=[], repository=_fake_repository(persona=None), chat_id=1
        )

    payload = session.post.call_args.kwargs["json"]
    assert payload["messages"][0]["content"] == SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_openrouter_client.py -v -k persona`
Expected: FAIL — `test_ask_ai_with_tools_appends_persona_to_system_prompt` fails because `"Отвечай дерзко и с юмором."` is not in the system content yet (the omits-persona test passes trivially before the change since there's no persona logic yet, so `-k persona` will show one FAIL and one PASS — that's expected at this stage).

- [ ] **Step 3: Implement the minimal code**

In `ai/openrouter_client.py`, inside `ask_ai_with_tools`, replace:

```python
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
```

with:

```python
    persona = await repository.get_persona(chat_id)
    system_content = SYSTEM_PROMPT
    if persona:
        system_content += (
            "\n\nДополнительно, стиль и характер общения в этом чате задал админ: "
            + persona
        )

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_openrouter_client.py -v`
Expected: PASS (all tests in the file — confirms existing `/ask` tests aren't broken by the new `get_persona` call)

- [ ] **Step 5: Commit**

```bash
git add ai/openrouter_client.py tests/test_openrouter_client.py
git commit -m "Append chat persona to /ask system prompt when configured"
```

---

### Task 4: `generate_violation_reaction` for trigger-word reactions

**Files:**
- Modify: `ai/openrouter_client.py` (add new function at end of file)
- Test: `tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: `config.OPENROUTER_API_KEY`, `config.OPENROUTER_MODEL`, `config.OPENROUTER_MAX_TOKENS`, `OPENROUTER_URL` (all already in this module)
- Produces: `generate_violation_reaction(persona: str, punishment: str, mute_minutes: int) -> Optional[str]` (`punishment` is one of `"warn"`/`"mute"`/`"kick"`) — used by Task 5 (`moderation/handlers.py`)

- [ ] **Step 1: Write the failing tests**

Add `import aiohttp` to the top of `tests/test_openrouter_client.py` (needed for the client-error test below):

```python
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
```

Add to `ai/openrouter_client.py`'s import list in the test file:

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
    generate_violation_reaction,
)
```

Add tests (end of file):

```python
async def test_generate_violation_reaction_returns_text_on_success(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "  Так, полегче там!  "}}]}
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_violation_reaction("Дерзкий стиль", "warn", mute_minutes=5)

    assert result == "Так, полегче там!"


async def test_generate_violation_reaction_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    result = await generate_violation_reaction("Дерзкий стиль", "warn", mute_minutes=5)

    assert result is None


async def test_generate_violation_reaction_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 500

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_violation_reaction("Дерзкий стиль", "kick", mute_minutes=5)

    assert result is None


async def test_generate_violation_reaction_returns_none_on_client_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("boom"))

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_violation_reaction("Дерзкий стиль", "mute", mute_minutes=10)

    assert result is None


async def test_generate_violation_reaction_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_violation_reaction("Дерзкий стиль", "mute", mute_minutes=10)

    assert result is None


async def test_generate_violation_reaction_returns_none_on_empty_content(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "   "}}]})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_violation_reaction("Дерзкий стиль", "warn", mute_minutes=5)

    assert result is None


async def test_generate_violation_reaction_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"unexpected": "shape"})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_violation_reaction("Дерзкий стиль", "warn", mute_minutes=5)

    assert result is None


async def test_generate_violation_reaction_includes_persona_and_punishment_in_prompt(monkeypatch):
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
        await generate_violation_reaction("Дерзкий стиль и юмор", "mute", mute_minutes=15)

    payload = session.post.call_args.kwargs["json"]
    prompt = payload["messages"][0]["content"]
    assert "Дерзкий стиль и юмор" in prompt
    assert "15 минут" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_openrouter_client.py -v -k generate_violation_reaction`
Expected: FAIL — `ImportError: cannot import name 'generate_violation_reaction'`

- [ ] **Step 3: Implement the minimal code**

In `ai/openrouter_client.py`, add at the end of the file:

```python


_REACTION_TIMEOUT = aiohttp.ClientTimeout(total=10)

_PUNISHMENT_OUTCOMES = {
    "warn": "получил предупреждение",
    "mute": "получил ограничение на отправку сообщений на {minutes} минут",
    "kick": "был удалён из чата",
}


async def generate_violation_reaction(
    persona: str, punishment: str, mute_minutes: int
) -> Optional[str]:
    """Single non-tool completion call for a moderation reaction line.

    Swallows every failure mode (missing key, non-200, network error,
    timeout, malformed/empty response) into None so the caller can fall
    back to the static punishment template without a try/except.
    """
    if not config.OPENROUTER_API_KEY:
        return None

    outcome = _PUNISHMENT_OUTCOMES[punishment].format(minutes=mute_minutes)
    task_prompt = (
        f"Характер бота в этом чате: {persona}\n"
        f"Пользователь нарушил правила чата и {outcome} за мат/оскорбления. "
        "Напиши одну короткую (1-2 предложения) реакцию в чат в этом стиле. "
        "Не обращайся к пользователю по имени и не добавляй никаких упоминаний — "
        "обращение бот добавит сам."
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
    except (aiohttp.ClientError, TimeoutError):
        return None

    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return None

    return text or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_openrouter_client.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add ai/openrouter_client.py tests/test_openrouter_client.py
git commit -m "Add generate_violation_reaction for persona-driven moderation text"
```

---

### Task 5: Wire persona-driven reactions into moderation handler

**Files:**
- Modify: `moderation/handlers.py:1-17` (imports), `moderation/handlers.py:100-117` (message-building block inside `handle_moderated_message`)
- Test: `tests/test_moderation_handlers.py`

**Interfaces:**
- Consumes: `Repository.get_persona` (Task 1), `generate_violation_reaction(persona, punishment, mute_minutes) -> Optional[str]` (Task 4)
- Produces: no new public symbols; `handle_moderated_message` behavior extended

- [ ] **Step 1: Write the failing tests**

Add `from unittest.mock import AsyncMock, patch` (extend the existing `from unittest.mock import AsyncMock` import) at the top of `tests/test_moderation_handlers.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
```

Add tests (end of file):

```python
async def test_reaction_uses_ai_when_persona_set(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value="Так, полегче там!"),
    ) as mock_generate:
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    mock_generate.assert_awaited_once_with("Дерзкий стиль", "warn", 5)
    message.answer.assert_awaited_once_with("User100, Так, полегче там!")


async def test_reaction_falls_back_to_template_when_ai_returns_none(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value=None),
    ):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    sent_text = message.answer.await_args.args[0]
    assert sent_text.startswith("User100, предупреждение")


async def test_reaction_escapes_html_from_ai_response(repo):
    bot = await make_bot()
    await repo.set_persona(chat_id=1, text="Дерзкий стиль")
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction",
        AsyncMock(return_value="<b>совсем оборзел</b>"),
    ):
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    message.answer.assert_awaited_once_with("User100, &lt;b&gt;совсем оборзел&lt;/b&gt;")


async def test_ai_not_called_when_no_persona_set(repo):
    bot = await make_bot()
    message = make_message("спам")

    with patch(
        "moderation.handlers.generate_violation_reaction", AsyncMock()
    ) as mock_generate:
        await handle_moderated_message(message, bot, repo, default_trigger_words=["спам"])

    mock_generate.assert_not_called()
    sent_text = message.answer.await_args.args[0]
    assert sent_text.startswith("User100, предупреждение")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_moderation_handlers.py -v -k reaction`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError: <module 'moderation.handlers'> does not have the attribute 'generate_violation_reaction'` (patch target doesn't exist yet), and `test_ai_not_called_when_no_persona_set` fails for the same reason.

- [ ] **Step 3: Implement the minimal code**

In `moderation/handlers.py`, update the import block at the top:

```python
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message

from admin.permissions import is_admin
from ai.openrouter_client import generate_violation_reaction
from db.repository import Repository
from moderation.logic import (
    compute_violation,
    contains_trigger_word,
    format_punishment_message,
    merge_trigger_words,
)
```

Then replace the message-building block inside `handle_moderated_message` (currently the code from the `# Only persist...` comment through `await message.answer(text)`):

```python
    # Only persist the new count once the enforcement action (if any) has
    # actually succeeded, so a permission failure doesn't silently advance
    # or reset the user's violation history.
    await repository.set_warning(
        message.chat.id, message.from_user.id, new_count, now.isoformat()
    )

    persona = await repository.get_persona(message.chat.id)
    reaction_text: Optional[str] = None
    if persona:
        reaction_text = await generate_violation_reaction(persona, punishment, mute_minutes)

    if reaction_text:
        text = f"{_mention(message)}, {html.escape(reaction_text)}"
    else:
        warn_message, mute_message, kick_message = await repository.get_message_templates(
            message.chat.id
        )
        custom_template = {"warn": warn_message, "mute": mute_message, "kick": kick_message}[
            punishment
        ]
        template = custom_template if custom_template else WARN_TEMPLATES[punishment]
        text = format_punishment_message(
            html.escape(template, quote=False), mention=_mention(message), minutes=mute_minutes
        )
    await message.answer(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_moderation_handlers.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — confirms the no-persona path is byte-for-byte unchanged)

- [ ] **Step 5: Commit**

```bash
git add moderation/handlers.py tests/test_moderation_handlers.py
git commit -m "Generate persona-driven trigger-word reactions with template fallback"
```

---

### Task 6: Full test suite sanity check

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-5
- Produces: confirmation the feature is fully wired with no regressions

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS — every test in `tests/` passes, including all pre-existing tests untouched by this plan (e.g. `tests/test_ai_handlers.py`, `tests/test_ai_tools.py`, `tests/test_broadcaster.py`, `tests/test_config.py`, `tests/test_content_filter.py`, `tests/test_group_commands.py`, `tests/test_logic.py`, `tests/test_permissions.py`).

- [ ] **Step 2: Manually re-read the diff against the spec**

Run: `git log --oneline -6` and `git diff HEAD~5 --stat` (adjust count if commit history differs) to confirm exactly these files changed: `db/repository.py`, `admin/commands.py`, `admin/bot_commands.py`, `ai/openrouter_client.py`, `moderation/handlers.py`, and their four test files, plus the spec/plan docs. No other files should appear.

No commit for this task — it's a verification checkpoint, not a code change.
