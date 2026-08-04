# Проактивные сообщения бота в чат (без команды) — дизайн

## Контекст

Сейчас бот пишет в чат только реактивно: в ответ на команду (`/ask` и т.п.) или на нарушение (триггер-слово → `WARN_TEMPLATES`/[[chat-persona]] реакция). Он никогда не инициирует сообщение сам.

Запрос: бот должен иногда сам «влезать» в переписку — как участник чата, а не справочная система — реагируя на последние сообщения в духе заданной через `/setpersona` персоны (`db.chat_settings.persona`, см. `docs/superpowers/specs/2026-08-03-chat-persona-design.md`). Периодичность/вероятность и объём контекста, на который бот реагирует, должны быть настраиваемыми per-chat, не хардкодом.

Функциональность полностью отделена от модерации: `compute_violation`, `handle_moderated_message`'ов существующий флоу наказаний, `/ask`-tool-calling — ничего из этого не меняется. Это третий, независимый источник исходящих сообщений от бота.

## Область

- Функция per-chat, **выключена по умолчанию** (`proactive_mode = 'off'`) — существующие чаты не получают новое поведение без явного действия админа.
- Ровно один режим на чат одновременно, выбирается админом:
  - **interval** — бот проверяет чат раз в N минут; если с прошлого раза были новые сообщения — реагирует; если в чате тишина — молчит.
  - **probability** — на каждое обычное сообщение в группе бросается кубик с вероятностью P; при удаче — бот реагирует.
- Если персона (`/setpersona`) не задана — проактивная функция для этого чата не работает вообще, даже если `proactive_mode != 'off'` (нечем задать характер реакции, чтобы не превращать бота в безликую справочную систему посреди чата).
- Контекст для реакции — последние N сообщений чата, где N настраивается отдельной командой (не хардкод «последнее сообщение»), диапазон 1–10.
- Жёсткий минимальный кулдаун между двумя проактивными отправками в одном чате (константа кода, не настройка) — защита от повторного срабатывания подряд (interval и probability случайно совпали, либо серия удачных бросков).
- Не проверяем/не модерируем сгенерированный ботом текст перед отправкой — тот же принцип доверия, что уже принят для `generate_violation_reaction`.
- Не сохраняем историю сообщений в БД — только in-memory буфер (см. ниже), персистентность истории между рестартами бота не нужна.

## Буфер последних сообщений (`proactive/buffer.py`, новый модуль)

Бот сейчас не хранит историю сообщений вообще — только транзитно видит их в хендлерах. Добавляется in-memory кольцевой буфer на чат:

```python
_BUFFER_CAP = 20  # >= максимально допустимого proactive_context_size (10)

@dataclass
class BufferedMessage:
    author: str       # message.from_user.full_name или username
    text: str
    message_id: int

_buffers: dict[int, deque[BufferedMessage]] = {}          # chat_id -> последние сообщения
_last_proactive_message_id: dict[int, int] = {}            # chat_id -> message_id, на который уже реагировали
_last_proactive_fired_at: dict[int, float] = {}             # chat_id -> monotonic-время последней отправки

def record_message(chat_id: int, author: str, text: str, message_id: int) -> None: ...
def get_recent(chat_id: int, n: int) -> list[str]: ...           # ["Имя: текст", ...], максимум n, в порядке от старых к новым
def latest_message_id(chat_id: int) -> Optional[int]: ...         # message_id самого нового сообщения в буфере
def has_new_since_last_fire(chat_id: int) -> bool: ...            # для interval-режима
def mark_fired(chat_id: int, message_id: int) -> None: ...        # вызывать с latest_message_id(chat_id) на момент реакции
def cooldown_elapsed(chat_id: int, floor_seconds: float) -> bool: ...
```

`record_message` вызывается на **каждое** текстовое сообщение группы, независимо от того, включена ли проактивность в этом чате — чтобы контекст уже был тёплым в момент, когда админ функцию включит. Буфер живёт в памяти процесса; при рестарте бота обнуляется — это осознанно принятый компромисс (см. «Границы»).

## Изменения в БД

Новые колонки `chat_settings` (тот же механизм `_MIGRATION_COLUMNS` + `ALTER TABLE ... ADD COLUMN`, что и у `persona`/`mute_minutes`):

```python
_MIGRATION_COLUMNS = {
    ...
    "proactive_mode": "TEXT NOT NULL DEFAULT 'off'",           # 'off' | 'interval' | 'probability'
    "proactive_interval_min": "INTEGER NOT NULL DEFAULT 0",
    "proactive_probability": "REAL NOT NULL DEFAULT 0.0",       # доля 0.0–1.0, не проценты
    "proactive_context_size": "INTEGER NOT NULL DEFAULT 3",     # 1–10
}
```

Новые методы `Repository` (по образцу `get_persona`/`set_persona`, `set_broadcast_interval`):

```python
async def get_proactive_settings(self, chat_id: int) -> ProactiveSettings   # dataclass/tuple с 4 полями выше
async def set_proactive_off(self, chat_id: int) -> None
async def set_proactive_interval(self, chat_id: int, minutes: int) -> None      # также сбрасывает mode='interval'
async def set_proactive_probability(self, chat_id: int, probability: float) -> None  # mode='probability'
async def set_proactive_context_size(self, chat_id: int, size: int) -> None
async def list_active_proactive_interval_chats(self) -> list[tuple[int, int]]   # (chat_id, interval_min), по образцу list_active_broadcast_chats — для бутстрапа планировщика при старте
```

## AI-генератор реакции (`ai/openrouter_client.py`)

Новая функция, по образцу уже существующей `generate_violation_reaction`:

```python
async def generate_proactive_message(persona: str, recent_messages: list[str]) -> Optional[str]:
    """Прямой запрос без tool-calling. Возвращает None при любой ошибке/таймауте/пустом ответе —
    вызывающий код просто ничего не отправляет."""
```

- Один прямой POST без `tools`/`tool_choice`, `aiohttp.ClientTimeout(total=10)` — тот же профиль, что у `generate_violation_reaction` (короткая недорогая генерация).
- User-промпт: «Характер бота в этом чате: {persona}. Вот последние сообщения переписки: {recent_messages, по одному на строку}. Напиши одну короткую (1–2 предложения) реплику в этот разговор от своего имени, в заданном характере — как будто ты участник чата, который решил вставить своё слово. Не здоровайся, не представляйся, не резюмируй переписку — просто естественная реплика по теме.»
- Все ошибки (`aiohttp.ClientError`, таймаут, не-200, пустой/отсутствующий `content`) перехватываются внутри и возвращают `None` — вызывающий код (и job планировщика, и хендлер сообщений) не должен падать из-за сбоя генерации.
- Результат отправляется через `html.escape()` перед `message.answer`/`bot.send_message`, как и `generate_violation_reaction` (непроверенный текст от модели, HTML `parse_mode`).

## Interval-режим (`scheduler/proactive.py`, новый модуль, по образцу `scheduler/broadcaster.py`)

```python
def _job_id(chat_id: int) -> str:
    return f"proactive_{chat_id}"

def schedule_chat_proactive(scheduler, bot, repository, chat_id: int, interval_minutes: int) -> None:
    # снять текущий job по id, если interval_minutes <= 0 — на этом остановиться (выключено)
    # иначе scheduler.add_job(_scheduled_proactive_job, "interval", minutes=interval_minutes,
    #                          id=_job_id(chat_id), args=[bot, repository, chat_id], replace_existing=True)

async def _scheduled_proactive_job(bot, repository, chat_id: int) -> None:
    # 1. persona = await repository.get_persona(chat_id); если пусто — return
    # 2. если не buffer.has_new_since_last_fire(chat_id) — return (в чате тишина)
    # 3. если не buffer.cooldown_elapsed(chat_id, _MIN_COOLDOWN_SECONDS) — return
    # 4. settings = await repository.get_proactive_settings(chat_id)
    # 5. recent = buffer.get_recent(chat_id, settings.proactive_context_size)
    # 6. text = await generate_proactive_message(persona, recent); если None — return
    # 7. попытка bot.send_message(chat_id, html.escape(text)); TelegramAPIError — залогировать и не падать
    # 8. buffer.mark_fired(chat_id, buffer.latest_message_id(chat_id))

async def load_scheduled_proactive(scheduler, bot, repository) -> None:
    # по образцу load_scheduled_broadcasts: итерация repository.list_active_proactive_interval_chats(),
    # schedule_chat_proactive для каждого
```

Регистрация в `bot.py` — рядом с существующим `await load_scheduled_broadcasts(scheduler, bot, repository)`, тем же `scheduler`, без нового инстанса `AsyncIOScheduler`.

## Probability-режим (хук в `moderation/handlers.py`)

Внутри `handle_moderated_message`, **после** записи сообщения в буфер (см. ниже) и после существующей логики модерации, независимо от того, было ли применено наказание:

```python
settings = await repository.get_proactive_settings(message.chat.id)
if settings.proactive_mode == "probability":
    persona = await repository.get_persona(message.chat.id)
    if (
        persona
        and random.random() < settings.proactive_probability
        and buffer.cooldown_elapsed(message.chat.id, _MIN_COOLDOWN_SECONDS)
    ):
        recent = buffer.get_recent(message.chat.id, settings.proactive_context_size)
        text = await generate_proactive_message(persona, recent)
        if text:
            await message.answer(html.escape(text))
            buffer.mark_fired(message.chat.id, message.message_id)
```

Бросок кубика проверяется для любого отправителя (включая админов) — буфер и проактивность не завязаны на права.

## Запись в буфер

`buffer.record_message(...)` вызывается один раз на входящее текстовое сообщение группы, в самом начале `handle_moderated_message` (до модерационной логики, чтобы попасть в контекст даже если это сообщение само станет поводом для наказания) — независимо от `proactive_mode` чата.

## Команды админа (`admin/commands.py`)

По образцу `cmd_setinterval`/`cmd_setpersona`, все через `_require_admin`:

```
/setproactive off              — выключить (значение по умолчанию)
/setproactive interval <N>     — режим interval, N минут (целое > 0)
/setproactive chance <P>       — режим probability, P целый процент 1–100 (хранится как P/100.0)
/setproactivecontext <N>       — сколько последних сообщений в контексте, целое 1–10
```

Валидация — тем же стилем, что `cmd_setinterval` (`command.args.strip().isdigit()` + понятное сообщение об использовании при ошибке). `/setproactive interval`/`chance` при успехе для interval-варианта дополнительно вызывает `schedule_chat_proactive(scheduler, bot, repository, chat_id, minutes)` — как `cmd_setinterval` делает для рассылок; при переключении с interval на probability (или на off) снимает существующий job тем же вызовом с `interval_minutes=0`.

Добавить в `admin/bot_commands.py::BOT_COMMANDS` описания обеих команд.

## Тестирование

- `proactive/buffer.py`: `record_message`/`get_recent` — обрезка по `n`, порядок, пустой чат; `has_new_since_last_fire` — до/после `mark_fired`; `cooldown_elapsed` — до истечения порога/после.
- `ai/openrouter_client.py`: `generate_proactive_message` — успешный ответ, таймаут/сетевая ошибка/не-200/пустой content → `None` (аналогично существующим тестам `generate_violation_reaction`).
- `scheduler/proactive.py`: `schedule_chat_proactive` — регистрация job с правильным interval/id, `interval_minutes=0` снимает job, `replace_existing` при повторном вызове; `_scheduled_proactive_job` — молчит без персоны, молчит без новых сообщений, молчит на кулдауне, отправляет и обновляет `mark_fired` при успехе, не падает при ошибке `send_message`.
- `moderation/handlers.py`: probability-хук — с моком `random.random()` проверить срабатывание/несрабатывание по порогу вероятности, отсутствие срабатывания без персоны, отсутствие срабатывания на кулдауне; existing-тесты модерации продолжают проходить без изменений (проактивность не влияет на warn/mute/kick флоу).
- `admin/commands.py`: все 4 варианта `/setproactive`/`/setproactivecontext` — успешные значения, невалидные аргументы, не-админ отклоняется; переключение режимов корректно (пере)регистрирует/снимает scheduler job.

## Границы (сознательно не делаем)

- Буфер сообщений — только in-memory, не персистится в БД. При рестарте бота контекст обнуляется, бот «забывает» разговор до последних сообщений после рестарта. Считаем это приемлемым: сама фича — «атмосферная», не критичная функциональность, ради которой не стоит вводить новую таблицу и дисковый I/O на каждое сообщение чата.
- Оба режима (interval и probability) взаимоисключающие на чат — нельзя одновременно «раз в 20 минут» и «2% шанс на сообщение». Если понадобится комбинация — отдельный дизайн.
- Не вводим «тихие часы»/расписание (например, не писать ночью) — вне запроса, можно добавить отдельной настройкой позже.
- Не различаем персону для проактивных сообщений от персоны `/ask`/реакций на нарушения — одна и та же `chat_settings.persona` на все три канала, как и было задумано в `docs/superpowers/specs/2026-08-03-chat-persona-design.md`.
- Не проверяем сгенерированный текст на промпт-инъекции или качество перед отправкой — тот же принцип доверия, что уже закреплён для `generate_violation_reaction`.
- Общий минимальный кулдаун (`_MIN_COOLDOWN_SECONDS`) — константа в коде, не настройка per-chat; менять по запросу пользователя, если понадобится.
