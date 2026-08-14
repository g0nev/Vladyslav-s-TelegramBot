from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import config
from history.fetch import _cache, fetch_chat_history


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


def _text_message(message_id, text, author_name="Аня"):
    return SimpleNamespace(
        id=message_id,
        text=text,
        file=None,
        sender=SimpleNamespace(first_name=author_name, title=None),
    )


def _audio_message(message_id, performer, title, duration, author_name="My Music"):
    return SimpleNamespace(
        id=message_id,
        text=None,
        file=SimpleNamespace(performer=performer, title=title, duration=duration, name=None),
        sender=SimpleNamespace(first_name=None, title=author_name),
    )


def _document_message(message_id, file_name, caption=None, author_name="My Music"):
    return SimpleNamespace(
        id=message_id,
        text=caption,
        file=SimpleNamespace(performer=None, title=None, duration=None, name=file_name),
        sender=SimpleNamespace(first_name=None, title=author_name),
    )


async def _async_iter(items):
    for item in items:
        yield item


def _fake_client(messages):
    client = MagicMock()
    client.iter_messages = MagicMock(return_value=_async_iter(messages))
    return client


async def test_fetch_chat_history_returns_placeholder_when_client_is_none():
    result = await fetch_chat_history(1, None)
    assert result == "История чата недоступна: userbot не настроен."


async def test_fetch_chat_history_formats_text_audio_and_document():
    messages = [
        _text_message(10, "го в кино", author_name="Аня"),
        _audio_message(11, "Rammstein", "Du Hast", 233),
        _document_message(12, "playlist.pdf", caption="плейлист на месяц"),
    ]
    client = _fake_client(messages)

    result = await fetch_chat_history(-1001535605520, client)

    assert "3 сообщений/файлов из последних 3" in result
    assert "1. Аня: го в кино" in result
    assert "2. [аудио] Rammstein — Du Hast (3:53)" in result
    assert "3. [файл] playlist.pdf — плейлист на месяц" in result
    assert "https://t.me/c/1535605520/10" in result
    assert "https://t.me/c/1535605520/11" in result


async def test_fetch_chat_history_skips_messages_without_text_or_file():
    messages = [SimpleNamespace(id=1, text=None, file=None, sender=None)]
    client = _fake_client(messages)

    result = await fetch_chat_history(1, client)

    assert result == (
        "В этом чате пока нет проиндексированной истории "
        "(нет текстовых сообщений или файлов)."
    )


async def test_fetch_chat_history_omits_link_for_plain_group_chat_id():
    messages = [_text_message(5, "привет")]
    client = _fake_client(messages)

    result = await fetch_chat_history(-123456789, client)

    assert "https://t.me" not in result


async def test_fetch_chat_history_uses_cache_within_ttl(monkeypatch):
    monkeypatch.setattr(config, "HISTORY_CACHE_TTL_SECONDS", 120)
    messages = [_text_message(1, "привет")]
    client = _fake_client(messages)

    first = await fetch_chat_history(1, client)
    client.iter_messages = MagicMock(side_effect=AssertionError("should not refetch"))
    second = await fetch_chat_history(1, client)

    assert first == second


async def test_fetch_chat_history_refetches_after_ttl_expires(monkeypatch):
    monkeypatch.setattr(config, "HISTORY_CACHE_TTL_SECONDS", 120)
    client = _fake_client([_text_message(1, "первое")])
    await fetch_chat_history(1, client)

    _cache[1] = (monotonic() - 121, _cache[1][1])
    client.iter_messages = MagicMock(return_value=_async_iter([_text_message(2, "второе")]))

    result = await fetch_chat_history(1, client)

    assert "второе" in result


async def test_fetch_chat_history_returns_friendly_message_on_client_error():
    client = MagicMock()
    client.iter_messages = MagicMock(side_effect=RuntimeError("boom"))

    result = await fetch_chat_history(1, client)

    assert result == "Не удалось получить историю чата (ошибка Telegram API)."
