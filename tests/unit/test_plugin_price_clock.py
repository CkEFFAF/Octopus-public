"""DeepSeek phase boundaries use Beijing dates and real transitions."""

from datetime import datetime

import pytest

from octop.infra.plugins.marketplace import _window, peak_state


@pytest.mark.parametrize(
    ("at", "in_peak", "reason", "next_at"),
    [
        ("2026-11-09T00:59:59Z", False, "weekday", "2026-11-09T01:00:00+00:00"),
        ("2026-11-09T01:00:00Z", True, "weekday", "2026-11-09T04:00:00+00:00"),
        ("2026-11-09T04:00:00Z", False, "weekday", "2026-11-09T06:00:00+00:00"),
        ("2026-11-09T06:00:00Z", True, "weekday", "2026-11-09T10:00:00+00:00"),
        ("2026-11-09T10:00:00Z", False, "weekday", "2026-11-10T01:00:00+00:00"),
        ("2026-11-06T10:00:00Z", False, "weekday", "2026-11-09T01:00:00+00:00"),
        ("2026-11-08T01:00:00Z", False, "weekend", "2026-11-09T01:00:00+00:00"),
        ("2026-10-01T01:00:00Z", False, "holiday", "2026-10-08T01:00:00+00:00"),
        ("2026-09-25T01:00:00Z", False, "holiday", "2026-09-28T01:00:00+00:00"),
    ],
)
def test_peak_boundaries(at: str, in_peak: bool, reason: str, next_at: str) -> None:
    value = peak_state(datetime.fromisoformat(at))
    assert value.in_peak is in_peak
    assert value.reason == reason
    assert value.next_change_at.isoformat() == next_at
    assert value.calendar_supported


def test_unknown_year_is_explicit() -> None:
    assert not peak_state(datetime.fromisoformat("2028-03-01T00:00:00Z")).calendar_supported


@pytest.mark.parametrize("value", [None, True, False, "", " ", "nan", "Infinity", -1])
def test_missing_or_invalid_percent_is_not_zero(value: object) -> None:
    assert _window({"percent": value}) is None


def test_percent_and_reset_normalization() -> None:
    window = _window({"percent": "105.5", "resetsAt": "2026-11-09T01:00:00Z"})
    assert window is not None
    assert window.percent == 105.5
    assert window.resets_at is not None
    assert _window({"percent": 0}) is not None


def test_invalid_reset_does_not_hide_valid_quota() -> None:
    window = _window({"percent": 12, "resetsAt": "2026-11-09T01:00:00"})
    assert window is not None
    assert window.resets_at is None
