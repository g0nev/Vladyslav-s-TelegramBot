from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.tools import (
    ADMIN_TOOL_NAMES,
    ADMIN_TOOLS,
    CONFIRMATION_TOOLS,
    PUBLIC_TOOL_NAMES,
    PUBLIC_TOOLS,
    TARGET_REQUIRED_TOOLS,
    execute_tool,
)
from db.repository import Repository


@pytest.fixture
async def repo(tmp_path):
    repository = await Repository.create(str(tmp_path / "test.db"))
    yield repository
    await repository.close()


def _ctx(repo, **overrides):
    ctx = dict(
        bot=AsyncMock(),
        repository=repo,
        scheduler=MagicMock(),
        chat_id=1,
        target_id=None,
        target_mention=None,
    )
    ctx.update(overrides)
    return ctx


def test_tool_sets_have_expected_shape():
    assert PUBLIC_TOOL_NAMES == {
        "list_trigger_words",
        "get_user_warnings",
        "list_broadcast_messages",
    }
    assert PUBLIC_TOOL_NAMES <= ADMIN_TOOL_NAMES
    assert len(ADMIN_TOOL_NAMES) == 19
    assert {"mute_user", "kick_user"} <= ADMIN_TOOL_NAMES
    assert {"set_mute_minutes", "set_kick_after", "set_max_tokens"} <= ADMIN_TOOL_NAMES
    assert CONFIRMATION_TOOLS == {"mute_user", "kick_user"}
    assert TARGET_REQUIRED_TOOLS == {
        "get_user_warnings",
        "reset_user_warnings",
        "mute_user",
        "kick_user",
    }


def test_all_schemas_are_wellformed():
    for schema in ADMIN_TOOLS:
        assert schema["type"] == "function"
        assert isinstance(schema["function"]["name"], str)
        assert "description" in schema["function"]
        assert schema["function"]["parameters"]["type"] == "object"


async def test_list_trigger_words_empty_and_filled(repo):
    assert await execute_tool("list_trigger_words", {}, **_ctx(repo)) == (
        "Дополнительных триггер-слов нет."
    )
    await repo.add_trigger_word(1, "спам")
    result = await execute_tool("list_trigger_words", {}, **_ctx(repo))
    assert "спам" in result


async def test_get_user_warnings_uses_target(repo):
    await repo.set_warning(1, 100, 2, "2026-07-17T00:00:00+00:00")
    result = await execute_tool(
        "get_user_warnings", {}, **_ctx(repo, target_id=100, target_mention="User100")
    )
    assert "User100" in result and "2" in result


async def test_list_broadcast_messages(repo):
    assert await execute_tool("list_broadcast_messages", {}, **_ctx(repo)) == (
        "Пул сообщений рассылки пуст."
    )
    await repo.add_broadcast_message(1, "привет")
    result = await execute_tool("list_broadcast_messages", {}, **_ctx(repo))
    assert "привет" in result


async def test_add_trigger_word(repo):
    result = await execute_tool("add_trigger_word", {"words": ["казино"]}, **_ctx(repo))
    assert "казино" in result
    assert await repo.list_trigger_words(1) == ["казино"]


async def test_add_trigger_word_escapes_html_in_result(repo):
    result = await execute_tool("add_trigger_word", {"words": ["<script>"]}, **_ctx(repo))
    assert "&lt;script&gt;" in result
    assert "<script>" not in result
    assert await repo.list_trigger_words(1) == ["<script>"]


async def test_add_trigger_word_rejects_empty(repo):
    result = await execute_tool("add_trigger_word", {"words": ["   "]}, **_ctx(repo))
    assert result == "Нужно указать хотя бы одно непустое слово."
    assert await repo.list_trigger_words(1) == []


async def test_add_trigger_word_rejects_missing_words_key(repo):
    result = await execute_tool("add_trigger_word", {}, **_ctx(repo))
    assert result == "Нужно указать хотя бы одно непустое слово."
    assert await repo.list_trigger_words(1) == []


async def test_add_trigger_word_adds_several_words_in_one_call(repo):
    result = await execute_tool(
        "add_trigger_word", {"words": ["спам", "реклама", "казино"]}, **_ctx(repo)
    )
    assert await repo.list_trigger_words(1) == ["казино", "реклама", "спам"]
    assert "спам" in result and "реклама" in result and "казино" in result


async def test_add_trigger_word_rejects_placeholder_pattern(repo):
    result = await execute_tool(
        "add_trigger_word",
        {"words": [f"матерное_слово_{i}" for i in range(1, 21)]},
        **_ctx(repo),
    )
    assert "плейсхолд" in result.lower()
    assert await repo.list_trigger_words(1) == []


async def test_add_trigger_word_rejects_crammed_single_string(repo):
    result = await execute_tool(
        "add_trigger_word", {"words": ["спам, реклама, казино"]}, **_ctx(repo)
    )
    assert "отдельным элементом" in result
    assert await repo.list_trigger_words(1) == []


async def test_delete_trigger_word(repo):
    await repo.add_trigger_word(1, "спам")
    result = await execute_tool("delete_trigger_word", {"words": ["спам"]}, **_ctx(repo))
    assert "удалено" in result
    assert await repo.list_trigger_words(1) == []


async def test_delete_trigger_word_reports_missing(repo):
    result = await execute_tool("delete_trigger_word", {"words": ["спам"]}, **_ctx(repo))
    assert "не найдено" in result


async def test_delete_trigger_word_deletes_several_words_in_one_call(repo):
    await repo.add_trigger_word(1, "спам")
    await repo.add_trigger_word(1, "реклама")
    await repo.add_trigger_word(1, "казино")
    result = await execute_tool(
        "delete_trigger_word", {"words": ["спам", "реклама", "казино"]}, **_ctx(repo)
    )
    assert await repo.list_trigger_words(1) == []
    assert "спам" in result and "реклама" in result and "казино" in result


async def test_delete_trigger_word_reports_found_and_missing_together(repo):
    await repo.add_trigger_word(1, "спам")
    result = await execute_tool(
        "delete_trigger_word", {"words": ["спам", "несуществующее"]}, **_ctx(repo)
    )
    assert "спам" in result and "удалено" in result
    assert "несуществующее" in result and "не найдено" in result
    assert await repo.list_trigger_words(1) == []


async def test_delete_trigger_word_rejects_empty(repo):
    result = await execute_tool("delete_trigger_word", {"words": ["   "]}, **_ctx(repo))
    assert result == "Нужно указать хотя бы одно непустое слово."


async def test_delete_trigger_word_rejects_missing_words_key(repo):
    result = await execute_tool("delete_trigger_word", {}, **_ctx(repo))
    assert result == "Нужно указать хотя бы одно непустое слово."


async def test_delete_trigger_word_rejects_crammed_single_string(repo):
    result = await execute_tool(
        "delete_trigger_word", {"words": ["спам, реклама, казино"]}, **_ctx(repo)
    )
    assert "отдельным элементом" in result


async def test_reset_user_warnings(repo):
    await repo.set_warning(1, 100, 3, "2026-07-17T00:00:00+00:00")
    result = await execute_tool(
        "reset_user_warnings", {}, **_ctx(repo, target_id=100, target_mention="User100")
    )
    assert "сброшен" in result
    count, _ = await repo.get_warning(1, 100)
    assert count == 0


async def test_set_reset_days(repo):
    result = await execute_tool("set_reset_days", {"days": 7}, **_ctx(repo))
    assert "7" in result
    _, reset_days = await repo.get_chat_settings(1)
    assert reset_days == 7


async def test_set_broadcast_interval_persists_and_schedules(repo):
    with patch("ai.tools.schedule_chat_broadcast") as sched:
        result = await execute_tool("set_broadcast_interval", {"minutes": 30}, **_ctx(repo))
    assert "30" in result
    sched.assert_called_once()
    interval, _ = await repo.get_chat_settings(1)
    assert interval == 30


async def test_add_broadcast_message(repo):
    result = await execute_tool("add_broadcast_message", {"text": "реклама"}, **_ctx(repo))
    assert "добавлено" in result
    assert await repo.list_broadcast_messages(1) == [(1, "реклама")]


async def test_add_broadcast_message_rejects_empty(repo):
    result = await execute_tool("add_broadcast_message", {"text": "  "}, **_ctx(repo))
    assert result == "Нужно указать непустой текст сообщения."
    assert await repo.list_broadcast_messages(1) == []


async def test_delete_broadcast_message_found_and_missing(repo):
    msg_id = await repo.add_broadcast_message(1, "x")
    assert "удалено" in await execute_tool(
        "delete_broadcast_message", {"message_id": msg_id}, **_ctx(repo)
    )
    assert "не найдено" in await execute_tool(
        "delete_broadcast_message", {"message_id": 999}, **_ctx(repo)
    )


async def test_set_punishment_messages(repo):
    assert "предупрежд" in (
        await execute_tool("set_warn_message", {"text": "стоп {mention}"}, **_ctx(repo))
    ).lower()
    assert "мьют" in (
        await execute_tool("set_mute_message", {"text": "мьют {mention}"}, **_ctx(repo))
    ).lower()
    assert "кик" in (
        await execute_tool("set_kick_message", {"text": "кик {mention}"}, **_ctx(repo))
    ).lower()
    warn, mute, kick = await repo.get_message_templates(1)
    assert warn == "стоп {mention}"
    assert mute == "мьют {mention}"
    assert kick == "кик {mention}"


async def test_set_warn_message_rejects_empty(repo):
    result = await execute_tool("set_warn_message", {"text": ""}, **_ctx(repo))
    assert result == "Нужно указать непустой текст."


async def test_reset_punishment_messages(repo):
    await repo.set_warn_message(1, "custom")
    result = await execute_tool("reset_punishment_messages", {}, **_ctx(repo))
    assert "сброшены" in result
    warn, _, _ = await repo.get_message_templates(1)
    assert warn is None


async def test_set_mute_minutes(repo):
    result = await execute_tool("set_mute_minutes", {"minutes": 15}, **_ctx(repo))
    assert "15" in result
    mute_minutes, _ = await repo.get_escalation_settings(1)
    assert mute_minutes == 15


async def test_set_mute_minutes_rejects_non_positive(repo):
    result = await execute_tool("set_mute_minutes", {"minutes": 0}, **_ctx(repo))
    assert result == "Нужно указать положительное число минут."


async def test_set_kick_after(repo):
    result = await execute_tool("set_kick_after", {"violations": 5}, **_ctx(repo))
    assert "5" in result
    _, kick_after = await repo.get_escalation_settings(1)
    assert kick_after == 5


async def test_set_kick_after_rejects_less_than_two(repo):
    result = await execute_tool("set_kick_after", {"violations": 1}, **_ctx(repo))
    assert result == "Кик может происходить не раньше 2-го нарушения."


async def test_set_max_tokens(repo):
    result = await execute_tool("set_max_tokens", {"tokens": 800}, **_ctx(repo))
    assert "800" in result
    assert await repo.get_max_tokens(1) == 800


async def test_set_max_tokens_rejects_below_minimum(repo):
    result = await execute_tool("set_max_tokens", {"tokens": 49}, **_ctx(repo))
    assert result == "Лимит токенов должен быть в диапазоне 50-3000."
    assert await repo.get_max_tokens(1) == 300


async def test_set_max_tokens_rejects_above_maximum(repo):
    result = await execute_tool("set_max_tokens", {"tokens": 3001}, **_ctx(repo))
    assert result == "Лимит токенов должен быть в диапазоне 50-3000."
    assert await repo.get_max_tokens(1) == 300


async def test_unknown_tool_returns_block_message(repo):
    result = await execute_tool("do_something_evil", {}, **_ctx(repo))
    assert result == "Не могу выполнить этот запрос."


def test_broadcast_tool_descriptions_distinguish_from_chat_content():
    descriptions = {
        schema["function"]["name"]: schema["function"]["description"] for schema in ADMIN_TOOLS
    }
    assert "read_chat_history" in descriptions["list_broadcast_messages"]
    assert "не связано с файлами" in descriptions["add_broadcast_message"]
    assert "не связано с файлами" in descriptions["delete_broadcast_message"]
