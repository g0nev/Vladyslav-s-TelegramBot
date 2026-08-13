# `/ask` читает содержимое чата (userbot-фетч истории) — дизайн

## Контекст

Баг-репорт: бот добавлен в канал "My Music" (только аудио-треки, ~500 штук). На `/ask подскажи рок песню... из тех что есть в канале` бот ответил дословно `Пул сообщений рассылки пуст.` — сырой текст инструмента `list_broadcast_messages` (`ai/tools.py:243-246`), который вообще не про содержимое канала, а про пул текстов для *автоматической рассылки самого бота* (`admin/commands.py` `/addmsg`/`/listmsgs`).

**Корневая причина (двойная):**

1. У модели в `/ask` нет ни одного инструмента, отвечающего за содержимое чата/канала — только модерация и рассылка (`ai/tools.py:29-193`). На вопрос про "то, что есть в канале" модель ошибочно выбрала ближайший по смыслу `list_broadcast_messages`.
2. Результат вызова инструмента из каталога `ai/tools.py` (`call_tool` в терминологии `ai/openrouter_client.py`) отправляется пользователю **как есть**, без второго прохода через модель (`ai/handlers.py:211-221`) — в отличие от мета-инструментов (`read_general_info`/`read_tools_reference`), чей результат возвращается модели для формулировки живого ответа (`ai/openrouter_client.py:332-346`). Поэтому даже правильный по смыслу, но нерелевантный вызов дал пользователю нечитаемый технический ответ.

Пользователь подтвердил реальную потребность: `/ask` должен уметь отвечать на вопросы **по содержимому** группы/канала (какие есть треки/файлы, что обсуждали и т.п.), включая уже существующие сообщения, а не только те, что придут после включения фичи.

**Ключевое ограничение Bot API:** боты не могут получить историю чата задним числом — `channel_post`/`message`-апдейты приходят только для новых событий. Единственный способ прочитать уже существующие ~500 треков — использовать MTProto-клиент (Telethon) от личного Telegram-аккаунта пользователя (userbot), у которого есть полноценный доступ к истории чата.

## Область

- Новый мета-инструмент `read_chat_history` в `/ask` (по образцу `read_general_info`) — модель вызывает его для вопросов про содержимое чата/канала, получает список сообщений/файлов и сама формулирует ответ.
- Данные читаются **живьём по запросу** через userbot (Telethon), лимит — последние 1000 сообщений чата. Никакого постоянного хранения в БД — ни бэкфилла, ни таблиц, ни синка на будущее.
- Индексируются два вида контента: обычный текст (`message.text`) и файлы (`message.audio`, `message.document`) — с их метаданными (title/performer/duration/file_name) и подписью (caption).
- Короткий in-memory кэш (не БД) на чат, чтобы несколько вопросов подряд об одном чате не били по Telegram API каждый раз.
- Точечный фикс описания `list_broadcast_messages`, чтобы модель больше не путала пул автоrассылки с содержимым чата (защита от повторения того же класса бага).

**Не делаем:**
- Никакого постоянного индекса/БД, никакого фонового бэкфилла при добавлении бота в чат, никакого `my_chat_member`-хендлера.
- Разбор фото/видео без подписи, распознавание жанра музыки по аудио-контенту (только по метаданным/названию — модель сама сопоставляет по своим знаниям).
- Поиск/фильтрация по ключевым словам на стороне БД — модель получает полный список (до 1000 позиций) и рассуждает над ним сама.

## Userbot-клиент (Telethon)

Новый модуль `history/telethon_client.py`:

```python
from telethon import TelegramClient

_client: Optional[TelegramClient] = None

async def start_client() -> Optional[TelegramClient]:
    """Возвращает подключённый клиент или None, если сессия не настроена/невалидна."""
    global _client
    if not (config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH and config.TELETHON_SESSION_STRING):
        return None
    client = TelegramClient(
        StringSession(config.TELETHON_SESSION_STRING),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    await client.connect()
    if not await client.is_user_authorized():
        return None
    _client = client
    return client
```

`bot.py::main()` вызывает `start_client()` один раз при старте, кладёт результат (может быть `None`) в `dp.start_polling(..., telethon_client=client)` — тот же DI-паттерн, что уже используется для `repository`/`scheduler`. Если клиент не поднялся (нет `.env`-переменных или сессия истекла) — бот работает как раньше, `read_chat_history` просто отвечает "история недоступна", ничего не падает.

**Новые переменные конфигурации** (`config.py`):
```python
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
TELETHON_SESSION_STRING = os.environ.get("TELETHON_SESSION_STRING", "")
HISTORY_FETCH_LIMIT = int(os.environ.get("HISTORY_FETCH_LIMIT", "1000"))
HISTORY_CACHE_TTL_SECONDS = int(os.environ.get("HISTORY_CACHE_TTL_SECONDS", "120"))
```

**Одноразовая генерация сессии** — новый скрипт `scripts/telethon_login.py`, запускается локально вручную (не на проде, интерактивный ввод телефона/кода/2FA):

```python
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID: "))
api_hash = input("API_HASH: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("Сохраните это значение в .env как TELETHON_SESSION_STRING:")
    print(client.session.save())
```

`API_ID`/`API_HASH` берутся с my.telegram.org на личный аккаунт. Session string — это полноценный доступ к аккаунту, хранить только в `.env` (не коммитить, добавить в `.gitignore`, если ещё не покрыто).

**Новая зависимость:** `requirements.txt` — `telethon>=1.36,<2`.

## Фетч и форматирование истории

Новый модуль `history/fetch.py`:

```python
_cache: dict[int, tuple[float, str]] = {}  # chat_id -> (fetched_at, formatted_text)

async def fetch_chat_history(chat_id: int, client: Optional[TelegramClient]) -> str:
    if client is None:
        return "История чата недоступна: userbot не настроен."

    cached = _cache.get(chat_id)
    if cached and time.monotonic() - cached[0] < config.HISTORY_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        messages = await _collect_messages(client, chat_id, config.HISTORY_FETCH_LIMIT)
    except Exception:
        return "Не удалось получить историю чата (ошибка Telegram API)."

    text = _format_messages(chat_id, messages)
    _cache[chat_id] = (time.monotonic(), text)
    return text
```

`_collect_messages` — тонкая обёртка над `client.iter_messages(chat_id, limit=...)`, вытаскивает из каждого сообщения: `id`, `date`, автора (`sender.first_name`/`sender.title` — как `_author_name` в `moderation/handlers.py:42-47`, тот же принцип), и по типу:
- `message.text` (или `message.caption`, если есть медиа) → `kind="text"`
- `message.audio` (Telethon: `message.audio.title`/`.performer`/`.duration`) → `kind="audio"`
- `message.document`/`message.file` без audio-атрибутов → `kind="document"`, имя файла из `message.file.name`

Сообщения без текста/подписи/файла (например, голое фото без подписи) пропускаются — вне области.

`_format_messages` собирает компактный пронумерованный список, каждая строка ≤ ~120 символов текста, плюс ссылка на сообщение (только для супергрупп/каналов, где `chat_id` имеет вид `-100...`):

```python
def _message_link(chat_id: int, message_id: int) -> Optional[str]:
    if chat_id > -1_000_000_000_000:
        return None
    internal_id = -chat_id - 1_000_000_000_000
    return f"https://t.me/c/{internal_id}/{message_id}"
```

Пример строки: `12. [аудио] Rammstein — Du Hast (3:53) — https://t.me/c/1535605520/989`.

Итог — строка вида:
```
В этом чате доступно {N} сообщений/файлов (показаны последние {min(N,1000)}):
1. ...
2. ...
...
```

## Интеграция с `/ask`

`ai/openrouter_client.py`:
- Новая константа `READ_CHAT_HISTORY = "read_chat_history"`, добавляется в `META_TOOLS` (рядом с `READ_GENERAL_INFO`, `ai/openrouter_client.py:35-48`) с описанием: *"Показать сообщения/файлы, которые реально есть в этом чате/канале (текст, аудио, документы) — вызывай для вопросов про содержимое чата: какие есть треки/файлы, что обсуждали, посоветовать что-то из уже присланного и т.п. Не путай с read_general_info (настройки бота) и с командами рассылки (это отдельный, не связанный с содержимым чата пул текстов)."*
- `ask_ai_with_tools` получает новый параметр `telethon_client: Optional[TelegramClient] = None`; в цикле обработки тулов (`ai/openrouter_client.py:332-337`) добавляется ветка:
  ```python
  elif name == READ_CHAT_HISTORY:
      reference_text = await fetch_chat_history(chat_id, telethon_client)
  ```
  Результат уходит в `messages` тем же путём, что и `read_general_info` — модель получает его как `role: tool` и формулирует финальный ответ сама (не сырой дамп).
- `ai/handlers.py::cmd_ask` получает `telethon_client` через DI (как сейчас получает `scheduler`) и прокидывает в `ask_ai_with_tools(...)`.
- `bot.py`: `dp.include_router(...)` не меняется; в `dp.start_polling(...)` добавляется `telethon_client=telethon_client`.

## Фикс корневого бага (`list_broadcast_messages`)

`ai/tools.py:36`, описание меняется с:
> "Показать пул сообщений автоматической рассылки."

на:
> "Показать пул текстов автоматической рассылки от лица бота (не файлы и не сообщения самого чата — для содержимого чата есть read_chat_history)."

Аналогичное уточнение — в `ADMIN_ONLY_TOOLS` для `add_broadcast_message`/`delete_broadcast_message` (`ai/tools.py:116-134`), чтобы модель не путала эти команды с содержимым чата ни в одну, ни в другую сторону.

## Обработка ошибок

- Нет `.env`-переменных для Telethon → `start_client()` возвращает `None`, `/ask` отвечает "история недоступна" только если явно спросят про содержимое чата (остальной функционал не затронут).
- Сессия истекла/отозвана (`is_user_authorized() == False`) → то же самое, `None`.
- Ошибка на самом фетче (сеть, `FloodWaitError`, чат не найден для этого аккаунта) → `fetch_chat_history` ловит исключение и возвращает пользователю понятный текст вместо падения хендлера.
- Личный аккаунт не состоит в чате (userbot не может получить `entity`) → тот же путь ошибки.

## Тестирование

- `history/fetch.py::_format_messages` — юнит-тесты на форматирование (текст/аудио/документ, обрезка длинных текстов, генерация/отсутствие ссылки для обычной группы vs супергруппы/канала).
- `history/fetch.py::fetch_chat_history` — тест на кэш (второй вызов в пределах TTL не дёргает `client.iter_messages` повторно — мокается через `AsyncMock`/фейковый асинхронный итератор), тест на `client=None` → сообщение о недоступности, тест на исключение из клиента → сообщение об ошибке, не падение.
- `ai/openrouter_client.py::ask_ai_with_tools` — новый тест: модель вызывает `read_chat_history`, результат идёт вторым `tool`-сообщением, следующий раунд возвращает текст (по аналогии с существующими тестами на `read_general_info`).
- `ai/tools.py` — тест не требуется (только правки строк описания, без изменения поведения `execute_tool`).
- Регрессия: весь существующий набор тестов остаётся зелёным — `telethon_client` везде опциональный параметр с дефолтом `None`.

## Известные ограничения

- Если у чата в Telegram включено "скрыть историю для новых участников", а личный аккаунт вступил в чат после этой настройки — Telethon может не увидеть сообщения до момента вступления. Для владельца/админа чата (обычный случай использования этого бота) это ограничение не действует.
- Каждый вызов `read_chat_history` вне окна кэша — реальный поход в Telegram API за до 1000 сообщений, это не мгновенно (секунды). Приемлемо для текущего масштаба (личный бот, несколько чатов).
- `HISTORY_FETCH_LIMIT=1000` — жёсткий потолок; в очень больших/активных чатах это будет "последние 1000", а не полная история.
