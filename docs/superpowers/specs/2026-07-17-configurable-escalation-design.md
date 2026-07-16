# Настраиваемые параметры эскалации наказаний — дизайн

## Контекст

Сейчас правила эскалации жёстко зашиты в коде:
- `moderation/handlers.py`: `MUTE_MINUTES = 5` (константа модуля).
- `moderation/logic.py::compute_violation`: 1-е нарушение → `warn`, 2-е → `mute`, 3-е и далее → `kick` (сброс на 0) — числа `1`/`2` и ветка `else` вшиты прямо в функцию.

Тексты наказаний уже настраиваются по чату (`/setwarnmsg` и т.д., см. `docs/superpowers/specs/2026-07-15-telegram-moderator-bot-design.md` доп. фичу от 2026-07-16). Эта задача добавляет настройку **самих параметров**, а не только текста: сколько минут длится мьют, и после какого по счёту нарушения происходит кик.

**Важно про порядок работы:** эта фича трогает `db/repository.py`, `moderation/logic.py`, `moderation/handlers.py` — те же файлы, которые параллельно может редактировать фоновый агент, реализующий tool-calling для `/ask` (см. `2026-07-17-ai-tool-calling-design.md`). Реализация этой спеки должна начаться **только после** того, как та фича будет полностью завершена и закоммичена, чтобы не редактировать одни и те же файлы одновременно в двух процессах.

## Область

- `mute_minutes` — длительность мьюта в минутах, по чату. Дефолт: 5 (как сейчас).
- `kick_after_violation` — после какого по счёту нарушения происходит кик, по чату. Дефолт: 3 (как сейчас). Должно быть **≥ 2** (нарушение №1 всегда остаётся предупреждением — иначе теряется смысл трёхступенчатой системы).
- Нарушения между 1-м (всегда `warn`) и `kick_after_violation`-м (всегда `kick`) — все получают `mute`. Например, если `kick_after_violation = 5`: 1=warn, 2=mute, 3=mute, 4=mute, 5=kick. Если `kick_after_violation = 2`: 1=warn, 2=kick (мьюта вообще не происходит — валидный кейс, если админ хочет более жёсткую политику).

## Изменения в БД

Новые колонки `chat_settings` (та же миграция через `ALTER TABLE ... ADD COLUMN`, что и для `warn_message`/`mute_message`/`kick_message`):

| Колонка | Тип | Дефолт |
|---|---|---|
| `mute_minutes` | `INTEGER NOT NULL` | `5` |
| `kick_after_violation` | `INTEGER NOT NULL` | `3` |

Новые методы `Repository` (отдельные от `get_chat_settings`, по тому же принципу, что и `get_message_templates` — не меняем существующую 2-элементную сигнатуру `get_chat_settings`, чтобы не трогать все места, где она уже используется):

```python
async def get_escalation_settings(self, chat_id: int) -> tuple[int, int]:  # (mute_minutes, kick_after_violation)
async def set_mute_minutes(self, chat_id: int, minutes: int) -> None
async def set_kick_after(self, chat_id: int, violations: int) -> None
```

## Изменения в `moderation/logic.py`

`compute_violation` получает новый необязательный параметр `kick_after: int = 3` (дефолт совпадает с текущим поведением — существующие тесты и вызовы без этого параметра продолжают работать без изменений):

```python
def compute_violation(
    current_count: int,
    last_violation_at: Optional[datetime],
    reset_days: int,
    now: datetime,
    kick_after: int = 3,
) -> tuple[int, str]:
    if last_violation_at is not None and reset_days > 0:
        if now - last_violation_at > timedelta(days=reset_days):
            current_count = 0

    new_count = current_count + 1

    if new_count == 1:
        return new_count, "warn"
    if new_count >= kick_after:
        return 0, "kick"
    return new_count, "mute"
```

## Изменения в `moderation/handlers.py`

- Убрать модульную константу `MUTE_MINUTES = 5` (источник истины теперь БД).
- В `handle_moderated_message`: рядом с уже существующим вызовом `repository.get_chat_settings(...)` добавить `mute_minutes, kick_after = await repository.get_escalation_settings(chat_id)`.
- Передать `kick_after=kick_after` в вызов `compute_violation(...)`.
- Заменить `until_date=now + timedelta(minutes=MUTE_MINUTES)` на `until_date=now + timedelta(minutes=mute_minutes)`.
- Заменить `minutes=MUTE_MINUTES` (аргумент `format_punishment_message`) на `minutes=mute_minutes` — чтобы плейсхолдер `{minutes}` в кастомных текстах наказаний показывал реально настроенное значение, а не старую константу.

## Новые админ-команды (`admin/commands.py`)

- `/setmuteminutes <N>` — только админ, `N` — целое положительное число (валидация как у `/setinterval`: `command.args.strip().isdigit()`). `repository.set_mute_minutes(chat_id, N)`.
- `/setkickafter <N>` — только админ, `N` — целое число **≥ 2** (отдельная проверка после `isdigit()`: `int(N) >= 2`, иначе — "Использование: /setkickafter <число ≥ 2>"). `repository.set_kick_after(chat_id, N)`.

Добавить обе в `admin/bot_commands.py` (`BOT_COMMANDS`).

## Связь с фичей tool-calling для `/ask`

После того как эта задача реализована, в `ai/tools.py` (модуль из фичи tool-calling, к тому моменту уже существующий) нужно добавить два новых ADMIN-инструмента: `set_mute_minutes(minutes: int)` и `set_kick_after(violations: int)`, по тому же паттерну, что и остальные настроечные инструменты (`set_reset_days` и т.п.) — админ сможет менять параметры эскалации через `/ask` на естественном языке, что и было исходным запросом пользователя. Это отдельный маленький шаг после реализации обеих текущих фич, не часть этой спеки напрямую.

## Тестирование

Та же схема: `db/repository.py` — тесты на реальном SQLite (`tmp_path`), включая тест миграции на "старой" БД (по аналогии с `test_migration_adds_columns_to_preexisting_db`). `moderation/logic.py::compute_violation` — юнит-тесты на несколько значений `kick_after` (3 — совпадает с текущим поведением, 2 — кик сразу после мьюта нет вообще, 5 — несколько подряд `mute`). `moderation/handlers.py` — обновить/добавить тесты, проверяющие, что мьют реально ставится на настроенное число минут (не всегда 5) и кик происходит на настроенном нарушении (не всегда 3-м).

## Границы (сознательно не делаем)

- Не делаем настраиваемым количество ступеней эскалации сверх "warn → несколько mute → kick" (например, добавить ещё одну ступень между mute и kick) — жёстко трёхтипная схема (warn/mute/kick) остаётся, настраиваются только пороги и длительность.
- Не валидируем верхнюю границу `mute_minutes`/`kick_after_violation` (админ технически может поставить `mute_minutes=100000` или `kick_after_violation=1000000`) — риск минимален (это же собственный чат админа), явного разумного потолка не вводим.
