from typing import Any

import pytest
from pydantic import ValidationError

from afandem.sandbox.calendar import (
    ClinicCalendar,
    closure,
    fixed_holidays,
    hours_for,
    in_ramadan,
    is_open,
    is_open_day,
    missing_fixed_holidays,
)

# The calendar of the dataset spec's example scenario (2026).
SPEC_EXAMPLE: dict[str, Any] = {
    "closed": ["Fri"],
    "hours": [{"open": "10:00", "close": "22:00"}],
    "ramadan": False,
    "holidays": [
        "2026-01-07",
        "2026-01-25",
        "2026-03-20",
        "2026-03-21",
        "2026-03-22",
        "2026-04-13",
        "2026-04-25",
        "2026-05-01",
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
        "2026-05-30",
        "2026-06-17",
        "2026-06-30",
        "2026-07-23",
        "2026-08-25",
        "2026-10-06",
    ],
}


def calendar(**overrides: Any) -> ClinicCalendar:
    return ClinicCalendar.model_validate({**SPEC_EXAMPLE, **overrides})


def test_friday_closed_saturday_open() -> None:
    cal = calendar()
    assert closure(cal, "2026-11-06", "12:00") == "closed_day"  # Friday
    assert not is_open_day(cal, "2026-11-06")
    assert closure(cal, "2026-11-07", "12:00") is None  # Saturday
    assert is_open(cal, "2026-11-07", "12:00")


def test_hours_are_half_open() -> None:
    cal = calendar()
    assert is_open(cal, "2026-11-04", "10:00")
    assert is_open(cal, "2026-11-04", "21:59")
    assert closure(cal, "2026-11-04", "22:00") == "outside_hours"
    assert closure(cal, "2026-11-04", "09:59") == "outside_hours"


def test_public_holiday_and_eid_dates_are_closed_days() -> None:
    cal = calendar()
    assert closure(cal, "2026-10-06", "12:00") == "closed_day"  # Armed Forces Day, a Tuesday
    assert closure(cal, "2026-03-21", "12:00") == "closed_day"  # an Eid date, a Saturday
    assert closure(cal, "2026-10-07", "12:00") is None


def test_split_evening_hours() -> None:
    cal = calendar(hours=[{"open": "10:00", "close": "14:00"}, {"open": "17:00", "close": "22:00"}])
    assert is_open(cal, "2026-11-04", "13:30")
    assert closure(cal, "2026-11-04", "15:00") == "outside_hours"
    assert is_open(cal, "2026-11-04", "18:00")


def test_ramadan_hours_when_flagged() -> None:
    cal = calendar(ramadan=True, holidays=[])
    assert hours_for(cal, "2027-02-10")[0].open == "21:00"
    assert closure(cal, "2027-02-10", "12:00") == "outside_hours"  # Wednesday noon
    assert closure(cal, "2027-02-10", "20:59") == "outside_hours"
    assert is_open(cal, "2027-02-10", "21:00")
    # The 21:00-01:00 session runs past midnight into the next date.
    assert is_open(cal, "2027-02-11", "00:30")
    assert closure(cal, "2027-02-11", "01:00") == "outside_hours"
    # Thursday night's session spills into Friday; Friday night itself is closed, so
    # Saturday 00:30 is outside hours.
    assert is_open(cal, "2027-02-12", "00:30")
    assert closure(cal, "2027-02-12", "21:30") == "closed_day"
    assert closure(cal, "2027-02-13", "00:30") == "outside_hours"


def test_ramadan_bounds_limit_ramadan_hours() -> None:
    cal = calendar(ramadan=True, ramadan_from="2027-02-08", ramadan_to="2027-03-09", holidays=[])
    assert in_ramadan(cal, "2027-02-08")
    assert not in_ramadan(cal, "2027-02-07")
    assert not in_ramadan(cal, "2027-03-10")
    assert is_open(cal, "2027-03-15", "12:00")  # regular hours after Ramadan
    assert closure(cal, "2027-03-01", "12:00") == "outside_hours"
    with pytest.raises(ValidationError):
        calendar(ramadan=True, ramadan_from="2027-03-09", ramadan_to="2027-02-08")


def test_session_until_midnight() -> None:
    cal = calendar(hours=[{"open": "22:00", "close": "00:00"}])
    assert is_open(cal, "2026-11-04", "23:30")
    assert closure(cal, "2026-11-05", "00:30") == "outside_hours"


def test_fixed_holidays_helpers() -> None:
    assert fixed_holidays(2026) == [
        "2026-01-07",
        "2026-01-25",
        "2026-04-25",
        "2026-05-01",
        "2026-06-30",
        "2026-07-23",
        "2026-10-06",
    ]
    assert missing_fixed_holidays(calendar(), 2026) == []
    assert missing_fixed_holidays(calendar(holidays=[]), 2026) == fixed_holidays(2026)
    # The state's list is authoritative: an unlisted fixed holiday is not closed.
    assert closure(calendar(holidays=[]), "2026-10-06", "12:00") is None


def test_calendar_rejects_unknown_keys_and_bad_values() -> None:
    with pytest.raises(ValidationError):
        calendar(open_on_friday=True)
    with pytest.raises(ValidationError):
        calendar(closed=["Friday"])
    with pytest.raises(ValidationError):
        calendar(hours=[{"open": "10:00", "close": "24:00"}])
    with pytest.raises(ValidationError):
        calendar(holidays=["2026-02-30"])
