from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from ai.openrouter_client import AIUnavailableError, ask_ai


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
