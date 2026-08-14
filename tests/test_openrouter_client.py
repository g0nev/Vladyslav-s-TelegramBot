import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

import config
from ai.openrouter_client import (
    CALL_TOOL,
    META_TOOLS,
    READ_CHAT_HISTORY,
    READ_GENERAL_INFO,
    READ_TOOLS_REFERENCE,
    SYSTEM_PROMPT,
    AIResponse,
    AIUnavailableError,
    ask_ai,
    ask_ai_with_tools,
    build_general_info,
    build_tools_reference,
    generate_proactive_message,
    generate_violation_reaction,
)


def _fake_repository(
    broadcast_interval=0,
    reset_days=0,
    templates=(None, None, None),
    escalation=(5, 3),
    persona=None,
    proactive=("off", 0, 0.0, 3),
):
    repository = MagicMock()
    repository.get_chat_settings = AsyncMock(return_value=(broadcast_interval, reset_days))
    repository.get_message_templates = AsyncMock(return_value=templates)
    repository.get_escalation_settings = AsyncMock(return_value=escalation)
    repository.get_persona = AsyncMock(return_value=persona)
    repository.get_proactive_settings = AsyncMock(return_value=proactive)
    return repository


def _make_session_cm(response: AsyncMock):
    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    return session_cm


async def test_ask_ai_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    with pytest.raises(AIUnavailableError):
        await ask_ai("Привет")


async def test_ask_ai_returns_content_on_success(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "  Привет!  "}}]}
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai("Привет")

    assert result == "Привет!"


async def test_ask_ai_raises_on_non_200_status(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 401

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        with pytest.raises(AIUnavailableError):
            await ask_ai("Привет")


async def test_ask_ai_raises_on_malformed_response(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"unexpected": "shape"})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        with pytest.raises(AIUnavailableError):
            await ask_ai("Привет")


async def test_ask_ai_with_tools_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    with pytest.raises(AIUnavailableError):
        await ask_ai_with_tools(
            "Привет", tools=[], repository=_fake_repository(), chat_id=1
        )


async def test_ask_ai_with_tools_returns_text(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "  Привет!  "}}]}
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai_with_tools(
            "Привет", tools=[], repository=_fake_repository(), chat_id=1
        )

    assert result.text == "Привет!"
    assert result.tool_name is None
    assert result.tool_arguments == {}


def _tool_call_response(name: str, arguments: str, call_id: str = "call_1") -> AsyncMock:
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "function": {"name": name, "arguments": arguments},
                            }
                        ],
                    }
                }
            ]
        }
    )
    return response


def _text_response(content: str) -> AsyncMock:
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": content}}]})
    return response


async def test_ask_ai_with_tools_parses_call_tool(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = _tool_call_response(
        CALL_TOOL, '{"name": "add_trigger_word", "arguments": {"word": "спам"}}'
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai_with_tools(
            "добавь слово спам", tools=[], repository=_fake_repository(), chat_id=1
        )

    assert result.tool_name == "add_trigger_word"
    assert result.tool_arguments == {"word": "спам"}
    assert result.text is None


async def test_ask_ai_with_tools_handles_bad_arguments_json(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = _tool_call_response(CALL_TOOL, "")

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai_with_tools(
            "сбрось тексты", tools=[], repository=_fake_repository(), chat_id=1
        )

    assert result.tool_name is None
    assert result.tool_arguments == {}


async def test_ask_ai_with_tools_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 500

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        with pytest.raises(AIUnavailableError):
            await ask_ai_with_tools(
                "Привет", tools=[], repository=_fake_repository(), chat_id=1
            )


async def test_ask_ai_with_tools_sends_only_meta_tools_in_payload(monkeypatch):
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

    real_tools = [{"type": "function", "function": {"name": "x"}}]
    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        await ask_ai_with_tools(
            "q", real_tools, repository=_fake_repository(), chat_id=1
        )

    payload = session.post.call_args.kwargs["json"]
    assert payload["tools"] == META_TOOLS
    assert payload["tool_choice"] == "auto"


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


async def test_ask_ai_with_tools_includes_prior_answer_as_assistant_turn(monkeypatch):
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
            "а как установить их",
            tools=[],
            repository=_fake_repository(),
            chat_id=1,
            prior_answer="Таймер реакции не установлен, проактивные действия выключены.",
        )

    payload = session.post.call_args.kwargs["json"]
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "Таймер реакции не установлен, проактивные действия выключены.",
    }
    assert payload["messages"][2] == {"role": "user", "content": "а как установить их"}


async def test_ask_ai_with_tools_omits_assistant_turn_without_prior_answer(monkeypatch):
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
            "Привет", tools=[], repository=_fake_repository(), chat_id=1
        )

    payload = session.post.call_args.kwargs["json"]
    assert len(payload["messages"]) == 2
    assert payload["messages"][1] == {"role": "user", "content": "Привет"}


async def test_ask_ai_with_tools_reads_reference_then_calls_tool(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    real_tools = [
        {
            "type": "function",
            "function": {
                "name": "mute_user",
                "description": "Замьютить пользователя.",
                "parameters": {
                    "type": "object",
                    "properties": {"minutes": {"type": "integer", "description": "Минуты."}},
                    "required": ["minutes"],
                },
            },
        }
    ]

    responses = [
        _tool_call_response(READ_TOOLS_REFERENCE, "{}"),
        _tool_call_response(CALL_TOOL, '{"name": "mute_user", "arguments": {"minutes": 10}}'),
    ]

    session = MagicMock()
    post_cms = []
    for resp in responses:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        post_cms.append(cm)
    session.post = MagicMock(side_effect=post_cms)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await ask_ai_with_tools(
            "замьють спамера", real_tools, repository=_fake_repository(), chat_id=1
        )

    assert result.tool_name == "mute_user"
    assert result.tool_arguments == {"minutes": 10}
    assert session.post.call_count == 2

    second_call_payload = session.post.call_args_list[1].kwargs["json"]
    tool_messages = [m for m in second_call_payload["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "mute_user" in tool_messages[0]["content"]


async def test_ask_ai_with_tools_reads_general_info_then_answers(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    responses = [
        _tool_call_response(READ_GENERAL_INFO, "{}"),
        _text_response("Разработчик — Владислав Звездаев."),
    ]

    session = MagicMock()
    post_cms = []
    for resp in responses:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        post_cms.append(cm)
    session.post = MagicMock(side_effect=post_cms)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    repository = _fake_repository(broadcast_interval=15, reset_days=7)
    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await ask_ai_with_tools(
            "кто тебя разработал?", [], repository=repository, chat_id=1
        )

    assert result.text == "Разработчик — Владислав Звездаев."
    repository.get_chat_settings.assert_awaited_once_with(1)
    repository.get_message_templates.assert_awaited_once_with(1)

    second_call_payload = session.post.call_args_list[1].kwargs["json"]
    tool_messages = [m for m in second_call_payload["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "Владислав Звездаев" in tool_messages[0]["content"]


async def test_ask_ai_with_tools_raises_after_max_rounds(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    responses = [_tool_call_response(READ_TOOLS_REFERENCE, "{}") for _ in range(3)]
    session = MagicMock()
    post_cms = []
    for resp in responses:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        post_cms.append(cm)
    session.post = MagicMock(side_effect=post_cms)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        with pytest.raises(AIUnavailableError):
            await ask_ai_with_tools(
                "что ты умеешь?", tools=[], repository=_fake_repository(), chat_id=1
            )


async def test_build_general_info_includes_developer_and_chat_settings():
    repository = _fake_repository(
        broadcast_interval=30,
        reset_days=14,
        templates=("Тише!", None, None),
    )

    info = await build_general_info(chat_id=42, repository=repository)

    assert "Владислав Звездаев" in info
    assert "22 года" in info
    assert "фронтенд-разработчик" in info
    assert "предупреждение" in info and "мьют" in info and "кик" in info
    assert "14 дн." in info
    assert "30 мин." in info
    assert "Тише!" in info
    assert "стандартный" in info
    assert "5 мин." in info
    assert "не задан (обычный стиль)" in info
    assert "выключены" in info
    repository.get_chat_settings.assert_awaited_once_with(42)
    repository.get_message_templates.assert_awaited_once_with(42)
    repository.get_escalation_settings.assert_awaited_once_with(42)
    repository.get_persona.assert_awaited_once_with(42)
    repository.get_proactive_settings.assert_awaited_once_with(42)


async def test_build_general_info_includes_persona_when_set():
    repository = _fake_repository(persona="Отвечай дерзко и с юмором.")

    info = await build_general_info(chat_id=1, repository=repository)

    assert "Отвечай дерзко и с юмором." in info
    assert "не задан (обычный стиль)" not in info


async def test_build_general_info_reflects_custom_escalation_settings():
    repository = _fake_repository(escalation=(20, 5))

    info = await build_general_info(chat_id=1, repository=repository)

    assert "20 мин." in info
    assert "5-е и далее" in info


async def test_build_general_info_kick_after_two_has_no_mute_stage():
    repository = _fake_repository(escalation=(5, 2))

    info = await build_general_info(chat_id=1, repository=repository)

    assert "2-е и далее" in info
    assert "мьют на" not in info


async def test_build_general_info_reflects_interval_proactive_mode():
    repository = _fake_repository(proactive=("interval", 15, 0.0, 5))

    info = await build_general_info(chat_id=1, repository=repository)

    assert "раз в 15 мин" in info
    assert "последние 5 сообщений" in info


async def test_build_general_info_reflects_probability_proactive_mode():
    repository = _fake_repository(proactive=("probability", 0, 0.05, 3))

    info = await build_general_info(chat_id=1, repository=repository)

    assert "5%" in info


async def test_build_general_info_includes_full_manual_command_list():
    repository = _fake_repository()

    info = await build_general_info(chat_id=1, repository=repository)

    assert "/setproactive" in info
    assert "/setpersona" in info
    assert "/pin" in info


def test_build_tools_reference_lists_name_description_and_args():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "mute_user",
                "description": "Замьютить пользователя.",
                "parameters": {
                    "type": "object",
                    "properties": {"minutes": {"type": "integer", "description": "Минуты."}},
                    "required": ["minutes"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_trigger_words",
                "description": "Показать триггер-слова.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    reference = build_tools_reference(tools)

    assert "mute_user: Замьютить пользователя." in reference
    assert "minutes (integer) (обязательный): Минуты." in reference
    assert "list_trigger_words: Показать триггер-слова." in reference
    assert "без аргументов" in reference


def test_build_tools_reference_empty_list():
    assert build_tools_reference([]) == "Нет доступных команд."


def test_system_prompt_requires_answering_every_part_of_compound_question():
    assert "несколько" in SYSTEM_PROMPT
    assert "каждый" in SYSTEM_PROMPT or "каждую" in SYSTEM_PROMPT


def test_system_prompt_requires_executing_available_tool_instead_of_describing_it():
    assert "call_tool" in SYSTEM_PROMPT
    assert "а не объясняй" in SYSTEM_PROMPT or "а не рассказывай" in SYSTEM_PROMPT


def test_system_prompt_forbids_placeholder_words():
    assert "плейсхолд" in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_tool_calls_on_plain_greeting():
    assert "приветствие" in SYSTEM_PROMPT
    assert "не вызывай ни один инструмент" in SYSTEM_PROMPT


def test_system_prompt_treats_discussion_as_text_not_tool_call():
    assert "рассужда" in SYSTEM_PROMPT.lower()
    assert "не вызывай ни один инструмент" in SYSTEM_PROMPT


def test_system_prompt_forbids_stalling_placeholder_reply():
    lowered = SYSTEM_PROMPT.lower()
    assert "подожди" in lowered or "секунду" in lowered
    assert "следующего хода" in lowered or "нет продолжения" in lowered


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


async def test_generate_violation_reaction_returns_none_on_json_decode_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        side_effect=json.JSONDecodeError("Expecting value", "", 0)
    )

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


async def test_generate_proactive_message_returns_text_on_success(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "  О, интересная тема!  "}}]}
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: как дела"])

    assert result == "О, интересная тема!"


async def test_generate_proactive_message_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

    result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 500

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_client_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("boom"))

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_empty_content(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "   "}}]})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"unexpected": "shape"})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_returns_none_on_json_decode_error(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", ["Аня: привет"])

    assert result is None


async def test_generate_proactive_message_includes_persona_and_recent_messages_in_prompt(
    monkeypatch,
):
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
        await generate_proactive_message(
            "Дерзкий стиль и юмор", ["Аня: го в кино", "Боря: не хочу"]
        )

    payload = session.post.call_args.kwargs["json"]
    prompt = payload["messages"][0]["content"]
    assert "Дерзкий стиль и юмор" in prompt
    assert "Аня: го в кино" in prompt
    assert "Боря: не хочу" in prompt


async def test_generate_proactive_message_handles_empty_recent_messages(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "Привет!"}}]})

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await generate_proactive_message("Дерзкий стиль", [])

    assert result == "Привет!"


def test_meta_tools_include_read_chat_history():
    names = {tool["function"]["name"] for tool in META_TOOLS}
    assert READ_CHAT_HISTORY in names


async def test_ask_ai_with_tools_reads_chat_history_then_answers(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    responses = [
        _tool_call_response(READ_CHAT_HISTORY, "{}"),
        _text_response("Вот забавный рок-трек из канала: Rammstein — Du Hast."),
    ]
    session = MagicMock()
    post_cms = []
    for resp in responses:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        post_cms.append(cm)
    session.post = MagicMock(side_effect=post_cms)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    fake_client = object()
    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        with patch(
            "ai.openrouter_client.fetch_chat_history",
            AsyncMock(return_value="1. [аудио] Rammstein — Du Hast"),
        ) as fetch_mock:
            result = await ask_ai_with_tools(
                "подскажи рок песню из тех что есть в канале",
                [],
                repository=_fake_repository(),
                chat_id=42,
                telethon_client=fake_client,
            )

    assert result.text == "Вот забавный рок-трек из канала: Rammstein — Du Hast."
    fetch_mock.assert_awaited_once_with(42, fake_client)

    second_call_payload = session.post.call_args_list[1].kwargs["json"]
    tool_messages = [m for m in second_call_payload["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "Rammstein" in tool_messages[0]["content"]


async def test_ask_ai_with_tools_defaults_telethon_client_to_none(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    responses = [_tool_call_response(READ_CHAT_HISTORY, "{}"), _text_response("ok")]
    session = MagicMock()
    post_cms = []
    for resp in responses:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        post_cms.append(cm)
    session.post = MagicMock(side_effect=post_cms)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        with patch(
            "ai.openrouter_client.fetch_chat_history", AsyncMock(return_value="нет данных")
        ) as fetch_mock:
            await ask_ai_with_tools(
                "что за музыка в канале", [], repository=_fake_repository(), chat_id=1
            )

    fetch_mock.assert_awaited_once_with(1, None)
