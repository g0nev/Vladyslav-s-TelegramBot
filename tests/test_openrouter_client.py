from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from ai.openrouter_client import AIResponse, AIUnavailableError, ask_ai, ask_ai_with_tools


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
        await ask_ai_with_tools("Привет", tools=[])


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
        result = await ask_ai_with_tools("Привет", tools=[])

    assert result.text == "Привет!"
    assert result.tool_name is None
    assert result.tool_arguments == {}


async def test_ask_ai_with_tools_parses_tool_call(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "add_trigger_word",
                                    "arguments": '{"word": "спам"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai_with_tools("добавь слово спам", tools=[])

    assert result.tool_name == "add_trigger_word"
    assert result.tool_arguments == {"word": "спам"}
    assert result.text is None


async def test_ask_ai_with_tools_handles_bad_arguments_json(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "reset_punishment_messages", "arguments": ""}}
                        ]
                    }
                }
            ]
        }
    )

    with patch(
        "ai.openrouter_client.aiohttp.ClientSession",
        return_value=_make_session_cm(response),
    ):
        result = await ask_ai_with_tools("сбрось тексты", tools=[])

    assert result.tool_name == "reset_punishment_messages"
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
            await ask_ai_with_tools("Привет", tools=[])


async def test_ask_ai_with_tools_sends_tools_in_payload(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})

    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    tools = [{"type": "function", "function": {"name": "x"}}]
    with patch("ai.openrouter_client.aiohttp.ClientSession", return_value=session_cm):
        await ask_ai_with_tools("q", tools)

    payload = session.post.call_args.kwargs["json"]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
