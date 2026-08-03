# Настраиваемая «личность» бота на чат (`/setpersona`) — дизайн

## Контекст

Сейчас в чате два места, где бот генерирует или подставляет текст с фиксированным поведением:

- `/ask` (`ai/openrouter_client.py::ask_ai_with_tools`) — единый `SYSTEM_PROMPT` на все чаты, стиль ответов не настраивается.
- Реакция на триггер-слова (`moderation/handlers.py::handle_moderated_message`) — текст наказания берётся из статичных шаблонов (`WARN_TEMPLATES` по умолчанию или кастомные `set_warn_message`/`set_mute_message`/`set_kick_message`), без участия ИИ.

Запрос: дать админу чата возможность одной командой задать общую инструкцию-характер («как боту разговаривать/реагировать»), которая одновременно влияет и на ответы `/ask`, и на реакцию при поимке мат-слова — вместо статичного шаблона ИИ сам сочиняет реакцию в заданном стиле. Пример инструкции: «реагируй на мат импульсивно, используй такие-то слова и придумывай свои».

Эскалация наказаний (warn → mute → kick, кто когда мьютится/кикается) остаётся полностью в коде (`moderation/logic.py::compute_violation`) и не меняется — персона влияет только на **текст** реакции, не на то, применяется ли наказание.

## Область

- Одна инструкция (persona) на чат, произвольный текст, максимум **500 символов**.
- Задаётся и очищается одной командой `/setpersona`, только админом.
- Если персона не задана — поведение бота полностью совпадает с текущим (ИИ на реакцию мата не дёргается вообще).
- Если персона задана:
  - `/ask` учитывает её в стиле ответов (сверх текущей логики выбора инструментов — та не меняется).
  - Реакция на триггер-слово генерируется ИИ в заданном стиле вместо статичного шаблона; при сбое — откат на текущий статичный шаблон.

## Изменения в БД

Новая колонка `chat_settings.persona TEXT` (тот же механизм миграции `ALTER TABLE ... ADD COLUMN`, что и у `warn_message`/`mute_message`/`kick_message`, добавляется в `_MIGRATION_COLUMNS` в `db/repository.py`).

Новые методы `Repository`:

```python
async def get_persona(self, chat_id: int) -> Optional[str]
async def set_persona(self, chat_id: int, text: Optional[str]) -> None
```

Реализация — по образцу `get_message_templates`/`set_warn_message`.

## Новая команда `/setpersona` (`admin/commands.py`)

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

Добавить в `admin/bot_commands.py::BOT_COMMANDS`:
`BotCommand(command="setpersona", description="Задать характер/стиль поведения бота, без текста — сбросить (админ)")`.

## Влияние на `/ask`

В `ai/openrouter_client.py::ask_ai_with_tools` перед сборкой `messages` подтягивается персона:

```python
persona = await repository.get_persona(chat_id)
system_content = SYSTEM_PROMPT
if persona:
    system_content += (
        "\n\nДополнительно, стиль и характер общения в этом чате задал админ: "
        + persona
    )
messages = [{"role": "system", "content": system_content}, {"role": "user", "content": question}]
```

Персона добавляется **поверх** `SYSTEM_PROMPT`, а не вместо него — правила выбора инструментов, формат Markdown, запрет на плейсхолдеры при `add_trigger_word` и т.д. остаются в силе всегда. Персона может изменить только тон/манеру финального ответа.

`check_hard_block` по-прежнему проверяет только вопрос пользователя к `/ask`, текст самой персоны не проверяется — админ уже может задавать произвольный текст в `set_warn_message` и т.п. без такой проверки, это та же модель доверия (админ — доверенная роль).

## Влияние на реакцию на триггер-слова

В `moderation/handlers.py::handle_moderated_message`, **после** того как `punishment` уже вычислен через `compute_violation` (код, не ИИ) и (если нужно) само действие mute/kick уже выполнено:

```python
persona = await repository.get_persona(message.chat.id)
reaction_text: Optional[str] = None
if persona:
    reaction_text = await generate_violation_reaction(persona, punishment, mute_minutes)

if reaction_text:
    text = f"{_mention(message)}, {html.escape(reaction_text)}"
else:
    warn_message, mute_message, kick_message = await repository.get_message_templates(message.chat.id)
    custom_template = {"warn": warn_message, "mute": mute_message, "kick": kick_message}[punishment]
    template = custom_template if custom_template else WARN_TEMPLATES[punishment]
    text = format_punishment_message(
        html.escape(template, quote=False), mention=_mention(message), minutes=mute_minutes
    )
await message.answer(text)
```

Новая функция в `ai/openrouter_client.py`:

```python
async def generate_violation_reaction(
    persona: str, punishment: str, mute_minutes: int
) -> Optional[str]:
    """Прямой запрос без tool-calling. Возвращает None при любой ошибке/таймауте/пустом ответе —
    вызывающий код откатывается на статичный шаблон."""
```

- Один прямой POST на `OPENROUTER_URL`, без `tools`/`tool_choice` — не нужен tool-calling для короткой реплики.
- `aiohttp.ClientTimeout(total=10)` — короче, чем у `/ask` (30 сек), т.к. вызывается синхронно в обработчике каждого группового сообщения и не должен ощутимо тормозить чат.
- Промпт-задача (user-сообщение к модели) формулируется без слова "мат" в требовании повторить его — что-то вроде: «Характер бота в этом чате: {persona}. Пользователь получил {punishment} (mute — на {mute_minutes} мин.) за нарушение правил чата. Напиши одну короткую (1–2 предложения) реакцию в чат в этом стиле. Не обращайся к пользователю по имени и не добавляй никаких упоминаний — обращение бот добавит сам.»
- Любое исключение (`aiohttp.ClientError`, таймаут, не-200 статус, отсутствие `content` в ответе, пустая строка после `.strip()`) — перехватывается внутри функции и приводит к `return None`, а не к исключению наружу. Вызывающий код в `moderation/handlers.py` не должен ловить `AIUnavailableError` — функция целиком поглощает ошибки, чтобы не рисковать уронить обработку группового сообщения.

Экранирование: `mention_html()` — доверенная HTML-ссылка от Telegram, вставляется как есть. Текст от ИИ — непроверенный контент, отправляется под дефолтным `parse_mode="HTML"`, поэтому обязательно `html.escape()` перед подстановкой (тот же принцип, что закреплён в коммите `31a2ef8` для остальных источников текста).

## Тестирование

- `db/repository.py`: тест миграции колонки `persona` на «старой» БД (по аналогии с существующими), `get_persona`/`set_persona` (включая сброс в `None`).
- `admin/commands.py`: `/setpersona` с текстом сохраняет, без текста сбрасывает, текст >500 символов отклоняется с понятным сообщением, не-админ получает отказ.
- `ai/openrouter_client.py`: `generate_violation_reaction` — успешный ответ возвращает `.strip()`-нутый текст; таймаут/ошибка сети/не-200/пустой content — все возвращают `None`, а не бросают исключение.
- `moderation/handlers.py`: без персоны — поведение не изменилось (существующие тесты продолжают проходить как есть); с персоной и успешной генерацией — отправленный текст равен `f"{mention}, {escaped_reaction}"`; с персоной, но `generate_violation_reaction` вернул `None` — откат на прежний шаблонный текст (mute/kick сами по себе уже применены до генерации текста и не зависят от её результата).

## Границы (сознательно не делаем)

- Не проверяем текст персоны на промпт-инъекции/джейлбрейк-паттерны (`check_hard_block`) — админ уже доверенная роль, которая может задавать произвольный текст в других местах без такой проверки.
- Не фильтруем и не модерируем содержимое ответа ИИ (реальные оскорбления/выдуманные слова/лексика) отдельным списком — полагаемся на то, что admin сознательно настраивает стиль для своего чата, и на встроенную модерацию модели через OpenRouter.
- Не делаем персону per-punishment (отдельно для warn/mute/kick) — одна инструкция задаёт стиль сразу для всех случаев и для `/ask`.
- Не даём управлять персоной через `/ask`-инструменты (`ai/tools.py`) — только прямая команда `/setpersona`, как и просил пользователь.
- Не вводим верхнюю проверку качества/цензуры сгенерированного текста перед отправкой (кроме HTML-экранирования) — если модель через OpenRouter откажется отвечать в духе инструкции, это проявится как `None` → штатный откат на шаблон, отдельно не диагностируется.
