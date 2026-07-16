import importlib

import pytest


def test_loads_bot_token_from_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BOT_TOKEN=test-token-123\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import config

    importlib.reload(config)

    assert config.BOT_TOKEN == "test-token-123"


def test_missing_bot_token_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import config

    with pytest.raises(KeyError):
        importlib.reload(config)
