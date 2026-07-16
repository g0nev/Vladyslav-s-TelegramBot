from datetime import datetime, timedelta

from moderation.logic import (
    compute_violation,
    contains_trigger_word,
    merge_trigger_words,
)


def test_contains_trigger_word_case_insensitive():
    assert contains_trigger_word("Это СПАМ сообщение", ["спам"]) is True


def test_contains_trigger_word_no_match():
    assert contains_trigger_word("Обычное сообщение", ["спам"]) is False


def test_contains_trigger_word_empty_list():
    assert contains_trigger_word("что угодно", []) is False


def test_merge_trigger_words_deduplicates():
    result = merge_trigger_words(["спам", "реклама"], ["РЕКЛАМА", "оскорбление"])
    assert result == sorted({"спам", "реклама", "оскорбление"})


def test_compute_violation_first_is_warn():
    count, punishment = compute_violation(0, None, reset_days=30, now=datetime(2026, 1, 1))
    assert (count, punishment) == (1, "warn")


def test_compute_violation_second_is_mute():
    count, punishment = compute_violation(
        1, datetime(2026, 1, 1), reset_days=30, now=datetime(2026, 1, 1, 1)
    )
    assert (count, punishment) == (2, "mute")


def test_compute_violation_third_is_kick_and_resets():
    count, punishment = compute_violation(
        2, datetime(2026, 1, 1), reset_days=30, now=datetime(2026, 1, 1, 1)
    )
    assert (count, punishment) == (0, "kick")


def test_compute_violation_resets_after_window_expires():
    old_violation = datetime(2026, 1, 1)
    now = old_violation + timedelta(days=31)
    count, punishment = compute_violation(2, old_violation, reset_days=30, now=now)
    assert (count, punishment) == (1, "warn")


def test_compute_violation_never_resets_when_reset_days_zero():
    old_violation = datetime(2020, 1, 1)
    now = datetime(2026, 1, 1)
    count, punishment = compute_violation(1, old_violation, reset_days=0, now=now)
    assert (count, punishment) == (2, "mute")
