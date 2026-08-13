# Поддержка каналов — дизайн

## Контекст

Бот сейчас реагирует только на апдейты типа `message`: `moderation/handlers.py:177` слушает `F.chat.type.in_({"group", "supergroup"})`, все команды в `admin/commands.py`/`admin/group_commands.py`/`ai/handlers.py` зарегистрированы через `@router.message(...)`. В канале посты приходят отдельным типом апдейта — `channel_post` — и Telegram Bot API туда `message` не присылает вообще. Поэтому все команды и модерация сейчас в каналах не работают, даже если бота туда добавить админом.

У `channel_post` есть принципиальное отличие от `message`: `from_user` всегда `None` (постит «сам канал», см. `sender_chat`), а отправить пост в канал в принципе может только тот, у кого есть право «публиковать посты» — то есть только админ. Значит, сам факт получения `channel_post` уже эквивалентен «это сделал админ», отдельно спрашивать `bot.get_chat_member` не нужно и нечем (нет `user_id`).

Пользователь подтвердил объём: **`/ask`, рассылки (`/setinterval`+`/addmsg`+…) и оба режима проактива** должны заработать в каналах. Модерация по триггер-словам (warn/mute/kick) в каналы сознательно не идёт — там нет «нарушителя»-пользователя, которого можно предупредить/замьютить/выгнать, наказывать физически некого.

## Область

- Новый тип чата, который обрабатывает бот — `channel` (в дополнение к уже поддерживаемым `private`/`group`/`supergroup`).
- В канале работает: `/ask`, все команды настройки рассылки и проактива (`admin/commands.py`), команды управления самим чатом (`/pin`, `/unpin`, `/chatinfo`, `/settitle`, `/setdescription`, `/setphoto`, `/newlink`, `/revokelink` из `admin/group_commands.py`).
- В канале НЕ работает: модерация по триггер-словам (`handle_moderated_message`), `/lock`/`/unlock` (права участников — понятие, которого в канале не существует). Эти команды в канале просто не регистрируются — бот их не увидит и не ответит, никакого вводящего в заблуждение «не хватает прав».
- `/warns`/`/resetwarns` регистрируются наравне с остальными командами `admin/commands.py` (для единообразия, чтобы не городить список исключений), но фактически всегда будут отвечать «ответьте этой командой на сообщение пользователя» — в канале нет реплаев с `from_user`, так что этот путь и так уже корректно обрабатывается существующим кодом без изменений.
- Буфер последних сообщений (`proactive/buffer.py`) начинает получать записи и из постов канала — это единственное, что нужно, чтобы оба режима проактива (`interval` и `probability`) заработали там же, без изменений в `scheduler/proactive.py` и в самом буфере.

## Механизм регистрации: dual-handler

aiogram позволяет навесить на одну и ту же функцию-хендлер два независимых декоратора-регистрации:

```python
@router.message(Command("addword"))
@router.channel_post(Command("addword"))
async def cmd_addword(...): ...
```

Оба декоратора возвращают исходную функцию без оборачивания, `router.resolve_used_update_types()` сам добавит `channel_post` в список апдейтов, которые бот запрашивает у Telegram — правки в `bot.py`/`dp.start_polling` не требуются.

Это применяется точечно к каждому хендлеру, который решено пускать в каналы (список — в разделе «Область» выше). Никакой общей абстракции/хелпера не вводится — двух строк декоратора на функцию достаточно, а не все хендлеры файла нужно менять одинаково (`/lock` и `/unlock` явно остаются как есть).

## `admin/permissions.py::require_admin`

```python
async def require_admin(message: Message, bot: Bot) -> bool:
    if message.chat.type == "channel":
        return True
    if message.from_user is None:
        return False
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("Эта команда доступна только администраторам чата.")
        return False
    return True
```

Один новый ранний `return True` для `chat.type == "channel"`. `is_admin()` (принимает `user_id`) не трогаем — он используется в местах, где `user_id` реально есть (модерация групп, `on_join_request_decision`).

## `ai/handlers.py::cmd_ask`

- Добавляется `@router.channel_post(Command("ask"))` вторым декоратором.
- Текущая ранняя проверка `if message.from_user is None: return` (`ai/handlers.py:122`) меняется на `if message.from_user is None and message.chat.type != "channel": return` — то есть в приватных чатах/группах отсутствие `from_user` по-прежнему означает «выходим», а в канале это ожидаемо и не блокирует обработку.
- Определение прав: `admin = True if message.chat.type == "channel" else await is_admin(bot, message.chat.id, message.from_user.id)` вместо безусловного вызова `is_admin` — в канале звать `is_admin` не с чем (нет `user_id`), а раз пост опубликован, права на уровне «сделать что угодно через /ask» и так есть.
- Остальной код функции не меняется. Ветка `TARGET_REQUIRED_TOOLS`/`CONFIRMATION_TOOLS` (нужен `target_id` из реплая на сообщение с `from_user`) в канале физически недостижима — реплай на пост канала тоже не имеет `from_user`, значит `target_id` останется `None` и код упрётся в уже существующий `TARGET_REQUIRED_MESSAGE` раньше, чем дойдёт до `message.from_user.id` при создании `PendingAction`. Отдельно это защищать не нужно (сценарий физически не наступает).

## `moderation/handlers.py`

Новый небольшой helper и новый хендлер для `channel_post`, без изменений в `handle_moderated_message` (она остаётся group/supergroup-only и по-прежнему требует `from_user`):

```python
def _author_name(message: Message) -> str:
    if message.from_user is not None:
        return message.from_user.full_name
    if message.sender_chat is not None:
        return message.sender_chat.title or "канал"
    return "канал"
```

- `handle_moderated_message` и `on_group_message` переходят на `_author_name(message)` вместо `message.from_user.full_name` при вызове `buffer.record_message` (само поведение для групп не меняется, `_author_name` для сообщения с `from_user` всегда вернёт то же самое имя).
- `_maybe_send_proactive_reaction`: guard `if message.from_user is None or message.text is None: return` (`moderation/handlers.py:140`) теряет часть про `from_user` — становится `if message.text is None: return`. Дальше по телу функции `from_user` не используется вообще (только `message.chat.id`, `message.answer`), так что больше ничего не меняется.
- Новый хендлер:

```python
@router.channel_post(F.text)
async def on_channel_post(message: Message, bot: Bot, repository: Repository) -> None:
    buffer.record_message(
        message.chat.id, _author_name(message), message.text, message.message_id
    )
    await _maybe_send_proactive_reaction(message, bot, repository)
```

Без вызова `handle_moderated_message` — модерация триггер-словами в каналы сознательно не идёт (см. «Область»). `default_trigger_words` в сигнатуру не добавляется, он здесь не нужен.

## `admin/commands.py`

Ко всем существующим `@router.message(Command(...))` в файле добавляется `@router.channel_post(Command(...))`: `addword`, `delword`, `listwords`, `warns`, `resetwarns`, `setresetdays`, `setinterval`, `setmuteminutes`, `setkickafter`, `addmsg`, `delmsg`, `listmsgs`, `setwarnmsg`, `setmutemsg`, `setkickmsg`, `resetmsgs`, `setpersona`, `setproactive`, `setproactivecontext`. Тела функций не меняются — все они уже принимают `message: Message` и работают через `message.chat.id`, который одинаково валиден что для группы, что для канала; авторизация идёт через уже пофикшенный `require_admin`.

## `admin/group_commands.py`

`@router.channel_post(Command(...))` добавляется к: `pin`, `unpin`, `newlink`, `revokelink`, `chatinfo`, `settitle`, `setdescription`, `setphoto`. Тела не меняются — это чистые вызовы Bot API (`pin_chat_message`, `set_chat_title`, …), одинаково работающие для группы и канала.

`lock`/`unlock` — без изменений, остаются `@router.message`-only. `ChatPermissions`/`set_chat_permissions` — понятие прав участников чата, которого в канале нет (Telegram вернёт ошибку метода, а не «не хватает прав», текущий catch на `TelegramAPIError` дал бы вводящее в заблуждение сообщение — проще не регистрировать вовсе).

`on_join_request`/`on_join_request_decision` — не трогаем, `chat_join_request` уже отдельный тип апдейта, одинаково приходящий что для групп, что для каналов, если у канала включены заявки на вступление.

## `scheduler/broadcaster.py`, `scheduler/proactive.py`, `db/repository.py`

Изменений нет. `send_broadcast`/`_scheduled_broadcast_job`/`_scheduled_proactive_job` уже работают только через `chat_id` (`bot.send_message(chat_id, ...)`), без обращения к участникам чата. `Repository` уже хранит все настройки (`chat_settings`, `broadcast_messages`, trigger words и т.д.) по `chat_id` без привязки к типу чата.

## Тестирование

- `admin/permissions.py::require_admin` — новый юнит-тест: `chat.type == "channel"` возвращает `True` без обращения к `bot.get_chat_member` (мок бота не должен вызываться).
- `ai/handlers.py::cmd_ask` — новый тест на `channel_post`-апдейт без `from_user`: команда отрабатывает, `admin` вычисляется как `True` без вызова `is_admin`; существующие тесты на `message` в группе/приватном чате продолжают проходить без изменений.
- `moderation/handlers.py` — тест на новый `on_channel_post`: пост канала пишется в буфер с `_author_name` = `sender_chat.title`; `_maybe_send_proactive_reaction` срабатывает/не срабатывает по тем же правилам (persona/probability/cooldown), что и для группового сообщения — просто источник апдейта другой. Отдельно — `handle_moderated_message` НЕ вызывается для `channel_post` (модерация не активируется).
- `admin/commands.py`, `admin/group_commands.py` — для 2–3 репрезентативных команд (например `cmd_addword`, `cmd_setinterval`, `cmd_pin`) добавить тест с `channel_post`-апдейтом, подтверждающий, что команда отрабатывает так же, как в группе, без реального `from_user`. Не дублировать весь набор тестов для каждой команды — механизм регистрации одинаковый и уже покрыт репрезентативными случаями.
- Регрессия: полный существующий набор тестов (группы/приват) должен остаться зелёным без изменений — правки везде аддитивные (новый декоратор, новая ранняя `return True`, ослабленный guard), ни один существующий путь для `message`-апдейтов не удаляется и не меняет семантику.

## Границы (сознательно не делаем)

- Модерация триггер-словами, warn/mute/kick — не переносится на посты каналов ни в каком виде (нет пользователя-нарушителя). Если понадобится хоть что-то похожее (например, автоудаление постов по стоп-словам) — это отдельный дизайн с другой моделью наказания (не «варн юзера», а «удалить пост»).
- `/lock`/`/unlock` — не адаптируются под каналы, там нет прав участников на ограничение.
- Не вводится отдельный `is_channel_admin`-подобный API-чек — уверенность в правах строится исключительно на факте получения `channel_post` (Telegram сам гарантирует, что писать в канал может только тот, у кого есть право постить).
- Комментарии в постах канала (обсуждения в привязанной группе) — это уже обычные сообщения в супергруппе, они и так полностью покрыты существующей логикой `group`/`supergroup`; отдельно этот кейс не рассматривается.
