# Живое общение в `/ask` + фикс подчёркиваний — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Сделать текстовые ответы `/ask` неформальными (обсуждение/мнение → живой текст, а не вызов инструмента) и починить баг, из-за которого имена команд без бэктиков теряют подчёркивания в Telegram-Markdown.

**Architecture:** Два независимых изменения в существующем коде, без новых файлов и без изменения архитектуры tool-calling: (1) переписывается текстовая константа `SYSTEM_PROMPT` в `ai/openrouter_client.py`; (2) в `ai/handlers.py` добавляется чистая функция `_wrap_tool_names`, которая пост-обрабатывает текстовый ответ модели перед отправкой в Telegram.

**Tech Stack:** Python, aiogram, pytest, regex (`re` из стандартной библиотеки).

## Global Constraints

- Спека: `docs/superpowers/specs/2026-08-04-ask-conversational-tone-design.md`.
- Не менять логику выбора/исполнения инструментов: `ask_ai_with_tools`, `META_TOOLS`, `execute_tool`, проверки прав в `cmd_ask` (`ai/handlers.py`) остаются как есть.
- Не трогать `/setpersona` и её текст — она по-прежнему добавляется поверх `SYSTEM_PROMPT`.
- Источник списка имён для оборачивания в бэктики — `ai.tools.ADMIN_TOOL_NAMES` (надмножество `PUBLIC_TOOL_NAMES`), а не отдельный новый список.
- Не переходить на `MarkdownV2`, не добавлять pinning провайдера OpenRouter, не менять модель — вне области этой задачи.

---

## File Structure

- Modify: `ai/openrouter_client.py` — новый текст `SYSTEM_PROMPT` (строки 71–103 на момент написания плана).
- Modify: `ai/handlers.py` — добавить `import re`, функцию `_wrap_tool_names`, применить её к тексту ответа в `cmd_ask`.
- Modify: `tests/test_openrouter_client.py` — обновить один prompt-substring тест, добавить один новый.
- Modify: `tests/test_ai_handlers.py` — добавить unit-тесты на `_wrap_tool_names` и один интеграционный тест на `cmd_ask`.

Новых файлов нет.

---

### Task 1: Переписать `SYSTEM_PROMPT`

**Files:**
- Modify: `ai/openrouter_client.py:71-103`
- Test: `tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: ничего нового.
- Produces: `SYSTEM_PROMPT: str` (та же сигнатура/имя, что и раньше) — используется в `ask_ai_with_tools` (не меняется) и импортируется тестами.

- [x] **Step 1: Обновить существующий тест на приветствие и добавить новый тест на границу «обсуждение vs действие»**

В `tests/test_openrouter_client.py` найти функцию (примерно строка 513):

```python
def test_system_prompt_forbids_tool_calls_on_plain_greeting():
    assert "приветствие" in SYSTEM_PROMPT
    assert "не вызывай инструменты" in SYSTEM_PROMPT
```

Заменить на:

```python
def test_system_prompt_forbids_tool_calls_on_plain_greeting():
    assert "приветствие" in SYSTEM_PROMPT
    assert "не вызывай ни один инструмент" in SYSTEM_PROMPT


def test_system_prompt_treats_discussion_as_text_not_tool_call():
    assert "рассужда" in SYSTEM_PROMPT.lower()
    assert "не вызывай ни один инструмент" in SYSTEM_PROMPT
```

(Остальные три существующих prompt-теста — `test_system_prompt_requires_answering_every_part_of_compound_question`, `test_system_prompt_requires_executing_available_tool_instead_of_describing_it`, `test_system_prompt_forbids_placeholder_words` — не трогать, новый текст промпта их не ломает.)

- [x] **Step 2: Прогнать тесты, убедиться что новые/изменённые падают**

Run: `pytest tests/test_openrouter_client.py -k "forbids_tool_calls_on_plain_greeting or treats_discussion_as_text" -v`
Expected: FAIL — `test_system_prompt_forbids_tool_calls_on_plain_greeting` падает на `assert "не вызывай ни один инструмент" in SYSTEM_PROMPT` (старый текст этой фразы не содержит), `test_system_prompt_treats_discussion_as_text_not_tool_call` падает аналогично.

- [x] **Step 3: Заменить `SYSTEM_PROMPT` в `ai/openrouter_client.py`**

Заменить блок (строки 71–103, от `SYSTEM_PROMPT = (` до закрывающей `)`) целиком на:

```python
SYSTEM_PROMPT = (
    "Ты — участник этого Telegram-чата, отвечаешь на вопросы по команде /ask. "
    "Общайся неформально и по-дружески, как обычный собеседник в переписке (в духе "
    "ChatGPT/Claude/Gemini), а не как техническая справочная система: живо, коротко по "
    "делу, без канцелярита, можно шутить в тон. Если пользователь спрашивает твоё мнение, "
    "зовёт что-то обсудить или посоветоваться — отвечай от себя своими словами, а не "
    "сухим перечислением.\n\n"
    "За кулисами (пользователь про них не знает и сам их не называет) у тебя есть три "
    "служебные функции: read_tools_reference() — каталог реальных команд бота с "
    "аргументами; read_general_info() — информация о боте, разработчике, логике "
    "модерации и текущих настройках этого чата; call_tool(name, arguments) — выполнение "
    "конкретной команды по её точному имени из каталога.\n\n"
    "Дёргай их только когда пользователь явно просит выполнить действие или прямо "
    "спрашивает про твои возможности/бота/настройки: «что ты умеешь», «какие есть "
    "команды» → read_tools_reference; вопрос про бота/разработчика/правила модерации/"
    "настройки чата → read_general_info; явная просьба выполнить модерационное действие "
    "(замьютить, кикнуть, добавить/удалить триггер-слово и т.п.) → сначала "
    "read_tools_reference, затем call_tool с точным именем команды из каталога.\n\n"
    "Если пользователь не просит действие, а рассуждает или советуется на тему "
    "(например «как думаешь, каких слов не хватает в стоп-листе» или «можно что-то ещё "
    "добавить или и так хватит?») — это не команда: обсуди с ним, предложи свои варианты "
    "обычным текстом и не вызывай ни один инструмент, пока он явно не подтвердит, что "
    "именно сделать. То же самое с простым приветствием («привет», «здарова» и т.п.), "
    "благодарностью или репликой не по делу — просто ответь в тон, без вызова "
    "инструментов и без перечисления своих возможностей по собственной инициативе.\n\n"
    "Результат read_general_info и read_tools_reference — справочные данные для тебя, а "
    "не готовый ответ: после получения отвечай кратко и по существу вопроса своими "
    "словами, не копируя и не пересказывая инструмент целиком, если явно не просили "
    "полную информацию обо всём сразу. Если в сообщении несколько разных вопросов — "
    "ответь на каждый из них, вызвав все нужные инструменты по очереди, прежде чем дать "
    "финальный ответ. Если вопрос можно закрыть, выполнив доступную команду (например "
    "list_trigger_words, чтобы показать реальный список слов) — вызови её через "
    "call_tool и покажи результат, а не объясняй пользователю, как вызвать команду "
    "самому.\n\n"
    "При вызове add_trigger_word никогда не подставляй шаблонные плейсхолдеры вида "
    "«слово_1», «слово_2» вместо реальных слов — указывай настоящие слова каждое "
    "отдельным элементом списка.\n\n"
    "Ответ форматируется как Markdown: имена инструментов и команд (например, "
    "mute_user) всегда оборачивай в обратные кавычки (`mute_user`), иначе символы "
    "подчёркивания в имени сломают отображение."
)
```

- [x] **Step 4: Прогнать весь файл тестов промпта, убедиться что всё зелёное**

Run: `pytest tests/test_openrouter_client.py -v`
Expected: PASS — все тесты, включая старые (`test_system_prompt_requires_answering_every_part_of_compound_question` и т.д.) и два из Step 1.

- [x] **Step 5: Commit**

```bash
git add ai/openrouter_client.py tests/test_openrouter_client.py
git commit -m "$(cat <<'EOF'
Make /ask SYSTEM_PROMPT conversational, add discussion-vs-action boundary

Casual discussion/opinion questions ("как думаешь, каких слов не хватает
в стоп-листе") were triggering read_tools_reference and dumping the raw
tool catalog instead of getting a plain-text reply. Reframe the prompt
around a friendly conversational identity first, tools second, with an
explicit rule that discussion/opinion questions get a text answer and no
tool call until the user confirms a concrete action.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Функция `_wrap_tool_names`

**Files:**
- Modify: `ai/handlers.py`
- Test: `tests/test_ai_handlers.py`

**Interfaces:**
- Consumes: `ADMIN_TOOL_NAMES: set[str]` из `ai.tools` (уже импортирован в `ai/handlers.py:22`).
- Produces: `_wrap_tool_names(text: str) -> str` — используется в Task 3 внутри `cmd_ask`.

- [x] **Step 1: Написать падающие unit-тесты**

Добавить в конец `tests/test_ai_handlers.py`:

```python
from ai.handlers import _wrap_tool_names


def test_wrap_tool_names_wraps_bare_name():
    assert _wrap_tool_names("вызовем list_trigger_words") == "вызовем `list_trigger_words`"


def test_wrap_tool_names_does_not_double_wrap_already_backticked_name():
    text = "используй `add_trigger_word` для этого"
    assert _wrap_tool_names(text) == text


def test_wrap_tool_names_leaves_unrelated_text_untouched():
    text = "привет, как дела?"
    assert _wrap_tool_names(text) == text


def test_wrap_tool_names_wraps_multiple_names_in_one_text():
    text = "команды: list_trigger_words и delete_trigger_word"
    expected = "команды: `list_trigger_words` и `delete_trigger_word`"
    assert _wrap_tool_names(text) == expected
```

(Импорт `from ai.handlers import _wrap_tool_names` добавить рядом с уже существующим `from ai.handlers import cmd_ask, on_ai_confirm` на строке 8 — можно объединить в один импорт.)

- [x] **Step 2: Прогнать тесты, убедиться что падают**

Run: `pytest tests/test_ai_handlers.py -k "wrap_tool_names" -v`
Expected: FAIL — `ImportError: cannot import name '_wrap_tool_names' from 'ai.handlers'`.

- [x] **Step 3: Реализовать `_wrap_tool_names`**

В `ai/handlers.py` добавить `re` в импорты (после строки 1 `from __future__ import annotations`):

```python
from __future__ import annotations

import re
import uuid
```

Добавить после блока констант сообщений (после строки `NO_RIGHTS_MESSAGE = "Не удалось: боту не хватает прав."` и перед `CANCELLED_MESSAGE = "Действие отменено."`, либо сразу после всех `*_MESSAGE` констант — конкретно после `CANCELLED_MESSAGE = "Действие отменено."` и перед `PENDING_ACTION_TTL = timedelta(minutes=10)`):

```python
_TOOL_NAME_PATTERN = re.compile(
    r"(?<!`)\b("
    + "|".join(re.escape(name) for name in sorted(ADMIN_TOOL_NAMES, key=len, reverse=True))
    + r")\b(?!`)"
)


def _wrap_tool_names(text: str) -> str:
    return _TOOL_NAME_PATTERN.sub(r"`\1`", text)
```

- [x] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `pytest tests/test_ai_handlers.py -k "wrap_tool_names" -v`
Expected: PASS — все 4 теста.

- [x] **Step 5: Commit**

```bash
git add ai/handlers.py tests/test_ai_handlers.py
git commit -m "$(cat <<'EOF'
Add _wrap_tool_names helper to force backticks around known tool names

Telegram's legacy Markdown parser treats a bare underscore pair as an
italics marker and strips both underscores, turning list_trigger_words
into listtriggerwords when the model forgets to wrap the name in
backticks itself. This regexes over ai.tools.ADMIN_TOOL_NAMES and wraps
any bare occurrence, independent of what the model actually output.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Применить `_wrap_tool_names` в `cmd_ask`

**Files:**
- Modify: `ai/handlers.py:121-130`
- Test: `tests/test_ai_handlers.py`

**Interfaces:**
- Consumes: `_wrap_tool_names(text: str) -> str` из Task 2.
- Produces: ничего нового наружу — это конечная точка интеграции.

- [x] **Step 1: Написать падающий интеграционный тест**

Добавить в конец `tests/test_ai_handlers.py`:

```python
async def test_text_response_wraps_tool_names_in_backticks(repo):
    message = make_message()
    response = AIResponse(text="используй list_trigger_words чтобы посмотреть список")
    with patch("ai.handlers.is_admin", AsyncMock(return_value=False)):
        with patch("ai.handlers.ask_ai_with_tools", AsyncMock(return_value=response)):
            await cmd_ask(message, cmd("привет"), AsyncMock(), repo, MagicMock())
    sent_text = message.answer.await_args.args[0]
    assert "`list_trigger_words`" in sent_text
```

- [x] **Step 2: Прогнать тест, убедиться что падает**

Run: `pytest tests/test_ai_handlers.py -k "wraps_tool_names_in_backticks" -v`
Expected: FAIL — `assert "\`list_trigger_words\`" in sent_text` не проходит, т.к. текст отправляется как есть, без обёртки.

- [x] **Step 3: Подключить `_wrap_tool_names` в `cmd_ask`**

В `ai/handlers.py` заменить (строки 121–130):

```python
    if response.tool_name is None:
        text = response.text or UNAVAILABLE_MESSAGE
        try:
            await message.answer(text, parse_mode="Markdown")
        except TelegramBadRequest:
            # Model output can contain unbalanced markdown (e.g. a lone "*"),
            # which Telegram's parser rejects outright. Fall back to plain text
            # rather than losing the reply entirely.
            await message.answer(text, parse_mode=None)
        return
```

на:

```python
    if response.tool_name is None:
        text = _wrap_tool_names(response.text or UNAVAILABLE_MESSAGE)
        try:
            await message.answer(text, parse_mode="Markdown")
        except TelegramBadRequest:
            # Model output can contain unbalanced markdown (e.g. a lone "*"),
            # which Telegram's parser rejects outright. Fall back to plain text
            # rather than losing the reply entirely.
            await message.answer(text, parse_mode=None)
        return
```

- [x] **Step 4: Прогнать тест и весь файл, убедиться что всё проходит**

Run: `pytest tests/test_ai_handlers.py -v`
Expected: PASS — все тесты файла, включая новый.

- [x] **Step 5: Прогнать весь набор тестов проекта**

Run: `pytest -v`
Expected: PASS — весь набор (обе задачи вместе не должны ломать ничего в `tests/test_bot_commands.py`, `tests/test_openrouter_client.py` и т.д.).

- [x] **Step 6: Commit**

```bash
git add ai/handlers.py tests/test_ai_handlers.py
git commit -m "$(cat <<'EOF'
Wire _wrap_tool_names into cmd_ask's text-reply path

Closes the loop on the underscore-stripping bug: every plain-text /ask
reply now gets known tool names force-wrapped in backticks before
hitting Telegram's Markdown parser, regardless of whether the model
remembered to do it itself.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
