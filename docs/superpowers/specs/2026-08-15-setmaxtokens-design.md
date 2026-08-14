# Настраиваемый лимит токенов (`/setmaxtokens`) — дизайн

## Контекст

Лимит длины ответа модели (`max_tokens` в запросе к OpenRouter) сейчас захардкожен на уровне процесса: `config.OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "300"))` (`config.py:13`), используется как есть в четырёх местах `ai/openrouter_client.py` (`ask_ai`, `ask_ai_with_tools`, `generate_violation_reaction`, `generate_proactive_message`). Изменить его можно только через переменную окружения и перезапуск бота.

Проект уже хранит другие числовые настройки за чат (длительность мьюта, интервал рассылки, порог кика и т.д.) в таблице `chat_settings` через `Repository`, с парой команд `get_chat_settings`/`set_*`, применяемых сразу, без перезапуска. Часть таких настроек (`set_mute_minutes`, `set_kick_after`, `set_reset_days`, `set_broadcast_interval` и др.) также продублирована в `ai/tools.py` как AI-инструменты, которые модель может вызвать через `/ask`.

Пользователь хочет управлять лимитом токенов так же — командой `/setmaxtokens «число»`, и чтобы то же самое можно было сделать через `/ask` (попросив бота словами).

## Область

- Лимит токенов становится настройкой **на чат** (не глобальной на процесс), по аналогии с остальными `chat_settings`.
- Новая команда `/setmaxtokens «число»` в `admin/commands.py`, только для админов чата (как остальные `/set*`).
- Новый AI-инструмент `set_max_tokens` в `ai/tools.py` (в `ADMIN_ONLY_TOOLS`), доступный только админам через `/ask`.
- Допустимый диапазон значения: **50–3000** (защита от опечаток/абсурдных значений, которые либо обрежут ответ до бессмысленности, либо неоправданно раздуют стоимость/задержку). Значение по умолчанию для новых и существующих чатов — 300 (текущее поведение не меняется, пока админ явно не поменяет).
- Не входит в область: `ask_ai` (функция без доступа к `chat_id`/`repository`, нигде не вызывается за пределами `ai/openrouter_client.py` и тестов) — остаётся на глобальном `config.OPENROUTER_MAX_TOKENS` как дефолт параметра.
- Не входит в область: переменная окружения `OPENROUTER_MAX_TOKENS` не убирается — остаётся дефолтным значением для чатов, у которых `max_tokens` в БД ещё не задан явно (миграция колонки проставит DEFAULT 300 независимо от env, это осознанное упрощение — см. «Альтернативы»).

## Хранение

`db/repository.py`:
- Новая колонка в `_MIGRATION_COLUMNS`: `"max_tokens": "INTEGER NOT NULL DEFAULT 300"`. Применяется тем же идемпотентным `ALTER TABLE ... ADD COLUMN` циклом, что и остальные поздние колонки (`persona`, `proactive_*`) — миграций руками не требуется.
- `async def get_max_tokens(self, chat_id: int) -> int` — как `get_persona`/аналоги, `SELECT max_tokens FROM chat_settings WHERE chat_id = ?` после `get_chat_settings(chat_id)` (для гарантии, что строка существует).
- `async def set_max_tokens(self, chat_id: int, tokens: int) -> None` — `UPDATE chat_settings SET max_tokens = ? WHERE chat_id = ?`, как `set_mute_minutes`.

## Команда `/setmaxtokens`

В `admin/commands.py`, по образцу `cmd_setmuteminutes`:

```python
@router.message(Command("setmaxtokens"))
@router.channel_post(Command("setmaxtokens"))
async def cmd_setmaxtokens(
    message: Message, command: CommandObject, bot: Bot, repository: Repository
) -> None:
    if not await _require_admin(message, bot):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /setmaxtokens «число, 50-3000»")
        return
    tokens = int(command.args.strip())
    if tokens < 50 or tokens > 3000:
        await message.answer("Использование: /setmaxtokens «число, 50-3000»")
        return
    await repository.set_max_tokens(message.chat.id, tokens)
    await message.answer(f"Лимит токенов ответа установлен: {tokens}.")
```

Регистрируется и на `message`, и на `channel_post` (проект уже поддерживает каналы для всех `admin/commands.py`).

## AI-инструмент `set_max_tokens`

`ai/tools.py`, добавление в `ADMIN_ONLY_TOOLS`:

```python
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
```

Ветка в `execute_tool()`, по образцу `set_mute_minutes`/`set_kick_after` — тот же диапазон, что и у слэш-команды, ошибка возвращается текстом (не исключением):

```python
if tool_name == "set_max_tokens":
    tokens = _as_int(arguments.get("tokens"))
    if tokens < 50 or tokens > 3000:
        return "Лимит токенов должен быть в диапазоне 50-3000."
    await repository.set_max_tokens(chat_id, tokens)
    return f"Лимит токенов ответа установлен: {tokens}."
```

Тул попадает только в `ADMIN_ONLY_TOOLS`, поэтому `/ask` от не-админа его не увидит (та же защита, что у `set_mute_minutes` и др.).

## Проброс значения в AI-клиент

`ai/openrouter_client.py`: три функции, у которых уже есть доступ к чату, получают keyword-параметр `max_tokens: int = config.OPENROUTER_MAX_TOKENS` и подставляют его вместо константы в теле запроса к OpenRouter:

- `ask_ai_with_tools(question, tools, *, repository, chat_id, ..., max_tokens=config.OPENROUTER_MAX_TOKENS)`
- `generate_violation_reaction(persona, punishment, mute_minutes, *, max_tokens=config.OPENROUTER_MAX_TOKENS)`
- `generate_proactive_message(persona, recent_messages, *, max_tokens=config.OPENROUTER_MAX_TOKENS)`

Дефолт-параметр сохраняет обратную совместимость: если где-то (тесты, будущие вызовы) функция вызвана без явного `max_tokens`, поведение не меняется.

Вызывающий код тянет значение из репозитория и передаёт его явно:

- `ai/handlers.py:cmd_ask` — `max_tokens = await repository.get_max_tokens(message.chat.id)` перед вызовом `ask_ai_with_tools`.
- `moderation/handlers.py` — оба места, где сейчас вызываются `generate_violation_reaction` и `generate_proactive_message` (реакция на нарушение и проактивный `probability`-режим); `chat_id` уже есть в обоих (`message.chat.id`), просто добавляется чтение `get_max_tokens` перед вызовом.
- `scheduler/proactive.py:_scheduled_proactive_job` — `chat_id` уже параметр функции, добавляется `get_max_tokens(chat_id)` перед вызовом `generate_proactive_message`.

## Реестр команд

`admin/bot_commands.py`: новая строка в `BOT_COMMANDS`:

```python
BotCommand(command="setmaxtokens", description="Лимит длины ответа ИИ в токенах, 50-3000 (админ)"),
```

Этот список — одновременно меню команд Telegram и источник каталога для AI-инструмента `read_tools_reference` (`ai/handlers.py`/`ai/openrouter_client.py`), так что бот сможет объяснить команду по запросу «какие есть команды».

## Обработка ошибок

- Невалидный ввод (не число, вне диапазона 50–3000) — что в слэш-команде, что в AI-инструменте, отвечает текстом с подсказкой, никаких исключений наружу.
- Права — команда и тул доступны только админам чата, как остальные `/set*`-настройки (`_require_admin` для команды, `ADMIN_ONLY_TOOLS`/`ADMIN_TOOL_NAMES` для AI-пути).
- Отсутствие OpenRouter-ключа/сетевые ошибки — не меняется, уже обрабатывается существующими `try/except` в `ai/openrouter_client.py`.

## Тестирование

- `tests/test_repository.py` — `get_max_tokens` возвращает дефолт 300 для нового чата; `set_max_tokens` меняет и переживает повторный `get_chat_settings`.
- `tests/test_admin_commands.py` — `/setmaxtokens` меняет значение при валидном вводе; отклоняет не-число, значение <50, значение >3000; отклоняет не-админа.
- `tests/test_ai_tools.py` (или `test_ai_handlers.py`, где уже тестируется `execute_tool`) — `set_max_tokens` тул: успешный путь и оба граничных случая (диапазон), проверка что тул отсутствует в `PUBLIC_TOOL_NAMES`.
- `tests/test_openrouter_client.py` — переданный `max_tokens` действительно попадает в JSON тела запроса для `ask_ai_with_tools`, `generate_violation_reaction`, `generate_proactive_message`; вызов без явного аргумента использует `config.OPENROUTER_MAX_TOKENS` (обратная совместимость).

## Альтернативы (отклонено)

- **Глобальная настройка на весь бот** (один env/DB-ключ вместо per-chat) — отклонено пользователем: в разных чатах разумны разные лимиты, и это ломало бы единообразие с остальными `chat_settings`-командами, которые все per-chat.
- **Без верхней/нижней границы** — отклонено: голая свобода админа поставить любое число создаёт риск случайно обрубить ответы почти до нуля или неоправданно раздуть стоимость/задержку без всякой защиты от опечатки.
