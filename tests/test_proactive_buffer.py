import pytest

import proactive.buffer as buffer


@pytest.fixture(autouse=True)
def clear_buffer():
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()
    yield
    buffer._buffers.clear()
    buffer._last_fired_message_id.clear()
    buffer._last_fired_at.clear()


def test_get_recent_empty_chat_returns_empty_list():
    assert buffer.get_recent(chat_id=1, n=3) == []


def test_record_message_then_get_recent_returns_formatted_lines():
    buffer.record_message(chat_id=1, author="Аня", text="привет", message_id=1)
    buffer.record_message(chat_id=1, author="Боря", text="как дела", message_id=2)

    assert buffer.get_recent(chat_id=1, n=2) == ["Аня: привет", "Боря: как дела"]


def test_get_recent_returns_at_most_n_most_recent_in_order():
    for i in range(5):
        buffer.record_message(chat_id=1, author="Аня", text=f"msg{i}", message_id=i)

    assert buffer.get_recent(chat_id=1, n=2) == ["Аня: msg3", "Аня: msg4"]


def test_buffer_caps_at_twenty_oldest_dropped():
    for i in range(25):
        buffer.record_message(chat_id=1, author="Аня", text=f"msg{i}", message_id=i)

    recent = buffer.get_recent(chat_id=1, n=20)
    assert recent[0] == "Аня: msg5"
    assert recent[-1] == "Аня: msg24"


def test_buffers_are_independent_per_chat():
    buffer.record_message(chat_id=1, author="Аня", text="чат 1", message_id=1)
    buffer.record_message(chat_id=2, author="Боря", text="чат 2", message_id=1)

    assert buffer.get_recent(chat_id=1, n=5) == ["Аня: чат 1"]
    assert buffer.get_recent(chat_id=2, n=5) == ["Боря: чат 2"]


def test_latest_message_id_returns_none_for_unknown_chat():
    assert buffer.latest_message_id(chat_id=999) is None


def test_latest_message_id_returns_newest():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=10)
    buffer.record_message(chat_id=1, author="Аня", text="b", message_id=11)

    assert buffer.latest_message_id(chat_id=1) == 11


def test_has_new_since_last_fire_false_for_unknown_chat():
    assert buffer.has_new_since_last_fire(chat_id=999) is False


def test_has_new_since_last_fire_true_before_any_fire():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)

    assert buffer.has_new_since_last_fire(chat_id=1) is True


def test_has_new_since_last_fire_false_after_mark_fired_with_latest():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)

    assert buffer.has_new_since_last_fire(chat_id=1) is False


def test_has_new_since_last_fire_true_again_after_new_message():
    buffer.record_message(chat_id=1, author="Аня", text="a", message_id=1)
    buffer.mark_fired(chat_id=1, message_id=1)
    buffer.record_message(chat_id=1, author="Аня", text="b", message_id=2)

    assert buffer.has_new_since_last_fire(chat_id=1) is True


def test_cooldown_elapsed_true_before_any_fire():
    assert buffer.cooldown_elapsed(chat_id=1) is True


def test_cooldown_elapsed_false_immediately_after_mark_fired():
    buffer.mark_fired(chat_id=1, message_id=1)

    assert buffer.cooldown_elapsed(chat_id=1) is False


def test_cooldown_elapsed_true_after_floor_seconds_pass(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(buffer, "monotonic", lambda: fake_time[0])

    buffer.mark_fired(chat_id=1, message_id=1)
    fake_time[0] += buffer.MIN_COOLDOWN_SECONDS + 1

    assert buffer.cooldown_elapsed(chat_id=1) is True


def test_try_acquire_cooldown_true_and_stamps_clock_when_not_cooling_down(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(buffer, "monotonic", lambda: fake_time[0])

    assert buffer.try_acquire_cooldown(chat_id=1) is True

    fake_time[0] += 1.0
    assert buffer.cooldown_elapsed(chat_id=1) is False


def test_try_acquire_cooldown_false_and_does_not_change_clock_when_cooling_down(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(buffer, "monotonic", lambda: fake_time[0])

    buffer.mark_fired(chat_id=1, message_id=1)
    stamped_at = buffer._last_fired_at[1]
    fake_time[0] += 1.0

    assert buffer.try_acquire_cooldown(chat_id=1) is False
    assert buffer._last_fired_at[1] == stamped_at
