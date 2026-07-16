# Расширение набора команд: управление группой — дизайн

## Контекст

Помимо модерации по триггер-словам и рассылки, Telegram Bot API позволяет боту с нужными admin-правами управлять самой группой: закреплять сообщения, временно блокировать чат, управлять инвайт-ссылками, менять название/фото/описание, одобрять заявки на вступление. Ранее это обсуждалось с пользователем как список возможностей; выбран следующий набор для реализации (остальное — вне рамок, включая назначение/снятие админки через бота и работу с наборами стикеров/темами форума):

1. Закрепление сообщений (`/pin`, `/unpin`)
2. Блокировка чата (`/lock`, `/unlock`)
3. Инвайт-ссылки (`/newlink`, `/revokelink`)
4. Информация о чате (`/chatinfo`)
5. Одобрение заявок на вступление (не команда, а обработчик события)
6. Название/фото/описание группы (`/settitle`, `/setphoto`, `/setdescription`)

**Эта фича не трогает `ai/*`, `moderation/actions.py` и не пересекается с параллельно реализуемой фичей tool-calling для `/ask`** — общая точка соприкосновения только `admin/bot_commands.py` (список команд для подсказки `/`) и `bot.py` (порядок роутеров), оба меняются аддитивно (дописать, не переписывать).

## Глобальные ограничения

- Все команды из этого списка, кроме `/chatinfo`, доступны **только админам** (проверка через уже существующий `admin.permissions.is_admin`).
- `/chatinfo` — read-only, доступна всем участникам чата.
- Боту для этих функций нужны дополнительные admin-права в самой группе (помимо уже используемых "ограничение участников"): **"Изменение профиля группы"** (для title/photo/description/permissions) и **"Добавление участников"** (для инвайт-ссылок). Это нужно явно описать в ручном runbook — если прав не хватает, соответствующая команда должна вернуть тот же паттерн "боту не хватает прав", что уже есть в `moderation/handlers.py` (ловим `TelegramAPIError`, отвечаем понятным текстом), а не падать с трассировкой.

## Новые колонки БД (`chat_settings`, миграция тем же способом, что и `warn_message`/`mute_message`/`kick_message` — `ALTER TABLE ... ADD COLUMN`, обёрнуто в `try/except sqlite3.OperationalError`)

| Колонка | Тип | Назначение |
|---|---|---|
| `saved_permissions_json` | `TEXT`, nullable | Права чата на момент `/lock`, чтобы `/unlock` восстановил их точно, а не сбросил на дефолт |
| `last_invite_link` | `TEXT`, nullable | Ссылка, созданная последним `/newlink`, чтобы `/revokelink` (без аргумента) знала, что отзывать |

Новые методы `Repository`:
```python
async def get_saved_permissions(self, chat_id: int) -> Optional[str]
async def set_saved_permissions(self, chat_id: int, permissions_json: Optional[str]) -> None
async def get_last_invite_link(self, chat_id: int) -> Optional[str]
async def set_last_invite_link(self, chat_id: int, link: Optional[str]) -> None
```

## Новый модуль `admin/group_commands.py`

Отдельный файл (не разрастаем `admin/commands.py`, который уже покрывает модерацию/рассылку/тексты наказаний) — свой `Router(name="group")`, подключается в `bot.py` рядом с `admin_router` (тоже до `moderation_router`, т.к. это команды, не должны попадать в общий текстовый обработчик).

### `/pin` (только админ, обязателен reply)

Без reply — ответ "Ответьте этой командой на сообщение, которое нужно закрепить." (как `/warns`). С reply — `bot.pin_chat_message(chat_id, message_id=reply.message_id)`, отловить `TelegramAPIError` → "Боту не хватает прав на закрепление сообщений."

### `/unpin` (только админ)

Если есть reply — `bot.unpin_chat_message(chat_id, message_id=reply.message_id)`. Если reply нет — `bot.unpin_chat_message(chat_id)` без `message_id` (Telegram сам открепляет последнее закреплённое). Та же обработка ошибок прав.

### `/lock` (только админ)

1. `chat = await bot.get_chat(chat_id)` → сериализовать `chat.permissions` в JSON, сохранить через `set_saved_permissions` (только если ещё не сохранено — повторный `/lock` без `/unlock` между ними не должен затереть оригинал новым "всё закрыто" состоянием).
2. `bot.set_chat_permissions(chat_id, permissions=ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False))`.
3. Ответ "Чат заблокирован — только админы могут писать."

*Примечание для реализации:* точный список полей `ChatPermissions` (какие именно `can_send_*` булевы поля существуют) зависит от версии aiogram — сверить с реально установленной (`aiogram>=3.4,<4` из `requirements.txt`) через `python -c "from aiogram.types import ChatPermissions; print(ChatPermissions.model_fields.keys())"` перед тем, как писать код, а не полагаться слепо на список выше.

### `/unlock` (только админ)

1. Прочитать `saved_permissions_json` через `get_saved_permissions`.
2. Если есть — распарсить JSON обратно в `ChatPermissions(**dict)`, применить через `set_chat_permissions`, затем `set_saved_permissions(chat_id, None)` (очистить).
3. Если нет (чат не был заблокирован через `/lock`) — применить разумный дефолт (`ChatPermissions` со всем `True`, кроме `can_pin_messages`/`can_change_info`/`can_invite_users` — эти обычно остаются только у админов даже в разблокированном чате).
4. Ответ "Чат разблокирован."

### `/newlink` (только админ)

`link = await bot.create_chat_invite_link(chat_id)` → `set_last_invite_link(chat_id, link.invite_link)` → ответить самой ссылкой.

### `/revokelink` (только админ)

Прочитать `last_invite_link`. Если пусто — "Сначала создайте ссылку через /newlink." Иначе `bot.revoke_chat_invite_link(chat_id, invite_link=last_link)`, затем `set_last_invite_link(chat_id, None)`, ответ "Ссылка отозвана."

### `/chatinfo` (доступно всем)

```python
count = await bot.get_chat_member_count(chat_id)
admins = await bot.get_chat_administrators(chat_id)
```
Ответ: количество участников + список админов (`member.user.mention_html()` для каждого, статус creator/administrator).

### `/settitle <текст>` (только админ)

Валидация как у `/addword` (не пусто после `strip()`). `bot.set_chat_title(chat_id, title)`.

### `/setdescription <текст>` (только админ)

Аналогично, `bot.set_chat_description(chat_id, description)`. Пустой текст разрешён (это очистка описания) — в отличие от `/settitle`, где пустое название Telegram не примет: не валидируем на непустоту, просто передаём как есть.

### `/setphoto` (только админ, фото с подписью `/setphoto`)

Хендлер регистрируется на `Command("setphoto")` — в aiogram `CommandFilter` проверяет и `message.caption`, так что команда сработает, если фото отправлено с подписью `/setphoto`. Обработчик:
```python
if not message.photo:
    await message.answer("Отправьте фото с подписью /setphoto.")
    return
largest = message.photo[-1]
file = await bot.download(largest.file_id)
await bot.set_chat_photo(chat_id, photo=BufferedInputFile(file.read(), filename="chat_photo.jpg"))
```

## Одобрение заявок на вступление

Не команда, а обработчик Telegram-события `chat_join_request` (приходит, только если в группе включены заявки на вступление — если не включены, событие никогда не приходит, обработчик просто не активируется, дополнительно ничего проверять не нужно).

```python
@router.chat_join_request()
async def on_join_request(request: ChatJoinRequest, bot: Bot) -> None:
```

При получении — отправить в чат сообщение с упоминанием заявителя и inline-кнопками "✅ Одобрить" / "❌ Отклонить" (callback_data `joinreq:{user_id}:approve` / `joinreq:{user_id}:decline`). По нажатию — проверить, что нажавший является админом (`is_admin`), затем `bot.approve_chat_join_request(chat_id, user_id)` или `bot.decline_chat_join_request(chat_id, user_id)`, отредактировать сообщение с результатом. Если нажал не админ — `callback.answer("Только админ может это решить.", show_alert=True)`, действие не выполняется.

Состояние не персистится (у Telegram уже есть свой список заявок — если бот перезапустится до того, как кто-то нажал кнопку, старое сообщение с кнопками просто перестанет работать корректно только если сама заявка успеет исчезнуть; в реальности `approve/decline_chat_join_request` можно вызвать в любой момент, пока заявка активна, независимо от состояния бота — значит персистентность не нужна, кнопки остаются рабочими и после перезапуска).

## Обновление `admin/bot_commands.py`

Добавить в `BOT_COMMANDS`: `pin`, `unpin`, `lock`, `unlock`, `newlink`, `revokelink`, `chatinfo`, `settitle`, `setdescription`, `setphoto` (10 новых команд, `/setphoto` без аргумента в описании — уточнить, что нужно с подписью к фото). `/ask` остаётся первым в списке (не переставляем).

## Тестирование

Та же схема, что и везде: `Repository` — реальный SQLite в `tmp_path`; `Bot` — `AsyncMock`/`MagicMock` с явным `side_effect`/`return_value` под каждый метод (`pin_chat_message`, `get_chat`, `set_chat_permissions`, `create_chat_invite_link` и т.д.). Для `/setphoto` — мокаем `bot.download` (возвращает `BytesIO`) и `bot.set_chat_photo`. Для `chat_join_request` — тест хендлера напрямую с сконструированным `ChatJoinRequest`-подобным объектом (`SimpleNamespace`, как в остальных тестах хендлеров), проверяя обе ветки (админ нажал / не админ нажал).

## Границы (сознательно не делаем)

- Не даём эти новые действия как инструменты ИИ в `/ask` в этой итерации — это отдельное решение на будущее, после того как основная фича tool-calling будет готова и обкатана.
- Не реализуем назначение/снятие админки через бота (`promoteChatMember`) и работу со стикерпаком/темами форума — по решению пользователя, не входит в текущий топ.
- `/lock`/`/unlock` работают с правами чата **целиком** (все стандартные permissions разом) — точечная блокировка одного типа контента (например, только медиа) не предусмотрена.
