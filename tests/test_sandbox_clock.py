from datetime import UTC, date, datetime, timedelta

import pytest

from afandem.sandbox.clock import (
    CAIRO,
    WEEKDAYS,
    as_date,
    days_between,
    egypt_dst_period,
    offset_str,
    parse_date,
    parse_now,
    parse_time,
    render_now,
    resolve,
    same_date,
    weekday_code,
    zoned,
)

WEDNESDAY = "2026-11-04"  # the spec example's `now`


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("today", "2026-11-04"),
        ("+0d", "2026-11-04"),
        ("+1d", "2026-11-05"),
        ("+2d", "2026-11-06"),
        ("-1d", "2026-11-03"),
        ("+30d", "2026-12-04"),
        ("+60d", "2027-01-03"),
        ("this:wed", "2026-11-04"),
        ("next:wed", "2026-11-11"),
        ("this:thu", "2026-11-05"),
        ("next:thu", "2026-11-05"),
        ("this:sun", "2026-11-08"),
        ("next:sun", "2026-11-08"),
        ("next:sat", "2026-11-07"),
        ("next:tue", "2026-11-10"),
        ("month:+1:1", "2026-12-01"),
        ("month:+1:2", "2026-12-02"),
        ("month:0:15", "2026-11-15"),
        ("month:0:last", "2026-11-30"),
        ("month:-1:last", "2026-10-31"),
        ("month:+2:1", "2027-01-01"),
        ("month:+3:last", "2027-02-28"),
        ("2026-11-08", "2026-11-08"),
    ],
)
def test_resolve_table_from_wednesday(spec: str, expected: str) -> None:
    assert resolve(spec, WEDNESDAY) == expected


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        ("2026-11-07", "2026-11-08"),  # Saturday: 1 day
        ("2026-11-08", "2026-11-15"),  # Sunday: a week, never today
        ("2026-11-09", "2026-11-15"),  # Monday
        ("2026-11-10", "2026-11-15"),  # Tuesday
        ("2026-11-11", "2026-11-15"),  # Wednesday
        ("2026-11-12", "2026-11-15"),  # Thursday
        ("2026-11-13", "2026-11-15"),  # Friday
    ],
)
def test_next_sunday_from_each_weekday(today: str, expected: str) -> None:
    assert resolve("next:sun", today) == expected
    assert 1 <= days_between(today, expected) <= 7


def test_this_sunday_said_on_a_sunday_is_today() -> None:
    assert resolve("this:sun", "2026-11-08") == "2026-11-08"
    assert resolve("next:sun", "2026-11-08") == "2026-11-15"


@pytest.mark.parametrize("start_offset", range(7))
@pytest.mark.parametrize("target", WEEKDAYS)
def test_weekday_specs_land_on_the_weekday_in_range(start_offset: int, target: str) -> None:
    today = date(2026, 11, 7) + timedelta(days=start_offset)
    upcoming = as_date(resolve(f"next:{target}", today))
    this = as_date(resolve(f"this:{target}", today))
    assert weekday_code(upcoming) == weekday_code(this) == target
    assert 1 <= (upcoming - today).days <= 7
    assert 0 <= (this - today).days <= 6


def test_dst_crossing_next_sunday() -> None:
    now = zoned("2027-04-28T10:00:00")
    assert offset_str(now) == "+02:00"
    assert resolve("next:sun", now) == "2027-05-02"
    assert offset_str(zoned("2027-05-02T10:00:00")) == "+03:00"


def test_aware_instants_resolve_on_the_cairo_date() -> None:
    # 22:30 UTC on Thursday 29 April 2027 is 01:30 on Friday 30 April in Cairo (summer time
    # began at local midnight); the UTC date would be a day early.
    late = datetime(2027, 4, 29, 22, 30, tzinfo=UTC)
    assert as_date(late) == date(2027, 4, 30)
    assert resolve("+1d", late) == "2027-05-01"
    assert resolve("next:sun", late) == "2027-05-02"
    # At the October fall-back, 21:30 UTC is 23:30 local on the same Thursday.
    assert as_date(datetime(2026, 10, 29, 21, 30, tzinfo=UTC)) == date(2026, 10, 29)


def test_zoned_rejects_skipped_and_repeated_local_times() -> None:
    with pytest.raises(ValueError, match="nonexistent"):
        zoned("2027-04-30T00:30:00")
    with pytest.raises(ValueError, match="ambiguous"):
        zoned("2027-10-28T23:30:00")
    assert offset_str(zoned("2027-10-28T22:59:00")) == "+03:00"
    assert offset_str(zoned("2027-04-30T01:00:00")) == "+03:00"


@pytest.mark.parametrize("year", range(2026, 2031))
def test_dst_rule_matches_zoneinfo(year: int) -> None:
    start, end = egypt_dst_period(year)
    assert weekday_code(start) == "fri"
    assert weekday_code(end) == "thu"

    def offset(day: date) -> str:
        return offset_str(datetime(day.year, day.month, day.day, 12, tzinfo=CAIRO))

    one = timedelta(days=1)
    assert (offset(start - one), offset(start)) == ("+02:00", "+03:00")
    assert (offset(end), offset(end + one)) == ("+03:00", "+02:00")


def test_dst_periods_2026_and_2027() -> None:
    assert egypt_dst_period(2026) == (date(2026, 4, 24), date(2026, 10, 29))
    assert egypt_dst_period(2027) == (date(2027, 4, 30), date(2027, 10, 28))


def test_parse_now_checks_weekday_and_offset() -> None:
    block = {"local": "2026-11-04T10:00:00", "tz": "Africa/Cairo", "weekday": "Wednesday"}
    now = parse_now(block)
    assert render_now(now) == {
        "local": "2026-11-04T10:00:00",
        "tz": "Africa/Cairo",
        "weekday": "Wednesday",
        "offset": "+02:00",
        "iso": "2026-11-04T10:00:00+02:00",
    }
    assert parse_now({**block, "offset": "+02:00"}) == now
    with pytest.raises(ValueError, match="weekday"):
        parse_now({**block, "weekday": "Thursday"})
    with pytest.raises(ValueError, match="offset"):
        parse_now({**block, "offset": "+03:00"})
    with pytest.raises(ValueError, match="tz"):
        parse_now({**block, "tz": "Europe/London"})
    summer = parse_now({"local": "2027-06-01T09:00:00", "tz": "Africa/Cairo"})
    assert render_now(summer)["offset"] == "+03:00"


def test_dates_compare_as_dates() -> None:
    evening = zoned("2026-11-04T23:30:00")
    assert same_date(evening, "2026-11-04")
    assert same_date(evening.astimezone(UTC), date(2026, 11, 4))
    assert not same_date("2026-11-04", "2026-11-05")
    assert days_between("2026-11-04", "2026-11-08") == 4
    assert days_between("2026-11-08", "2026-11-04") == -4


@pytest.mark.parametrize(
    "bad", ["20261104", "2026-2-03", "2026-02-30", "٢٠٢٦-١١-٠٤", " 2026-11-04"]
)
def test_parse_date_is_strict(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_date(bad)


def test_parse_time_is_strict() -> None:
    assert parse_time("15:30").hour == 15
    for bad in ("24:00", "3:30", "15:30:00", "١٥:٣٠"):
        with pytest.raises(ValueError):
            parse_time(bad)


@pytest.mark.parametrize("bad", ["+2", "next:sunday", "this:Sun", "tomorrow", "month:0:31", "+1w"])
def test_unknown_or_impossible_specs_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        resolve(bad, WEDNESDAY)
