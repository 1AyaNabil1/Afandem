"""Scenario clock: a zoned Africa/Cairo `now`, relative-date specs, and dates compared as dates.

Egypt keeps daylight saving time from the last Friday of April (00:00 becomes 01:00) to the
last Thursday of October (24:00 becomes 23:00). Every computation here works on local calendar
dates, never on UTC instants plus hours, so a DST change between `now` and a target date cannot
move the target by a day.

Relative-date specs (what scenario authors write; `resolve` turns them into ISO dates):

- `YYYY-MM-DD`: that date.
- `today`: the local date of `now`.
- `+Nd` / `-Nd`: N days after / before (N up to 999).
- `this:sun`: the Sunday 0-6 days ahead (today when today is Sunday).
- `next:sun`: the Sunday 1-7 days ahead (a week ahead when today is Sunday).
- `month:+1:1`: day 1 of next month; `month:0:15`, `month:0:last`, `month:-1:last` likewise.

Weekdays are written `sat sun mon tue wed thu fri`.
"""

import calendar as _calendar
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CAIRO_TZ = "Africa/Cairo"
CAIRO = ZoneInfo(CAIRO_TZ)

# Indexed by date.weekday() (Monday == 0).
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_LOCAL_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2})?")
_DAYS_SPEC = re.compile(r"([+-])([0-9]{1,3})d")
_WEEKDAY_SPEC = re.compile(r"(this|next):(sat|sun|mon|tue|wed|thu|fri)")
_MONTH_SPEC = re.compile(r"month:([+-]?[0-9]{1,2}):([0-9]{1,2}|last)")

type DateLike = date | datetime | str


def parse_date(value: str) -> date:
    """Strict `YYYY-MM-DD` with ASCII digits (`date.fromisoformat` alone also takes `20261104`)."""
    if not _DATE_RE.fullmatch(value):
        raise ValueError(f"not an ISO date (YYYY-MM-DD): {value!r}")
    return date.fromisoformat(value)


def parse_time(value: str) -> time:
    """Strict 24-hour `HH:MM` with ASCII digits."""
    if not _TIME_RE.fullmatch(value):
        raise ValueError(f"not a time (HH:MM): {value!r}")
    return time.fromisoformat(value)


def as_date(value: DateLike) -> date:
    """The local Cairo calendar date of a value.

    Aware datetimes are converted to Cairo first; naive datetimes are taken as Cairo wall-clock
    time; strings are ISO dates or ISO datetimes (with or without an offset).
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(CAIRO).date()
    if isinstance(value, date):
        return value
    if _DATE_RE.fullmatch(value):
        return parse_date(value)
    return as_date(datetime.fromisoformat(value))


def same_date(a: DateLike, b: DateLike) -> bool:
    """Compare as Cairo calendar dates, never as instants."""
    return as_date(a) == as_date(b)


def days_between(start: DateLike, end: DateLike) -> int:
    """Calendar days from `start` to `end` (negative when `end` is earlier)."""
    return (as_date(end) - as_date(start)).days


def weekday_code(value: DateLike) -> str:
    """`sat`, `sun`, ... for the local date."""
    return WEEKDAYS[as_date(value).weekday()]


def weekday_name(value: DateLike) -> str:
    """`Saturday`, `Sunday`, ... for the local date."""
    return WEEKDAY_NAMES[as_date(value).weekday()]


def zoned(local: str | datetime, tz: str = CAIRO_TZ) -> datetime:
    """Attach the zone to a naive local wall-clock time.

    Raises `ValueError` for a time the DST change skips (Friday 00:00-00:59 in late April) or
    repeats (Thursday 23:00-23:59 in late October): a scenario `now` must be unambiguous.
    """
    if isinstance(local, str):
        if not _LOCAL_RE.fullmatch(local):
            raise ValueError(f"not a local ISO datetime (YYYY-MM-DDTHH:MM[:SS]): {local!r}")
        naive = datetime.fromisoformat(local)
    else:
        naive = local
    if naive.tzinfo is not None:
        raise ValueError("expected a naive local time")
    zone = ZoneInfo(tz)
    first = naive.replace(tzinfo=zone, fold=0)
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError(f"nonexistent local time (DST gap) in {tz}: {naive.isoformat()}")
    if naive.replace(tzinfo=zone, fold=1).utcoffset() != first.utcoffset():
        raise ValueError(f"ambiguous local time (DST overlap) in {tz}: {naive.isoformat()}")
    return first


def offset_str(moment: datetime) -> str:
    """The UTC offset of an aware datetime as `+02:00` / `+03:00`."""
    offset = moment.utcoffset()
    if offset is None:
        raise ValueError("expected an aware datetime")
    minutes = int(offset.total_seconds()) // 60
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{mins:02d}"


def parse_now(spec: Mapping[str, object]) -> datetime:
    """Validate a scenario `now` block and return the aware datetime.

    The block is `{"local": "2026-11-04T10:00:00", "tz": "Africa/Cairo", "weekday": "Wednesday"}`,
    optionally with `"offset": "+02:00"`; the weekday and offset are checked against the zone.
    """
    local = spec.get("local")
    if not isinstance(local, str):
        raise ValueError("now.local must be a string")
    tz = spec.get("tz", CAIRO_TZ)
    if tz != CAIRO_TZ:
        raise ValueError(f"now.tz must be {CAIRO_TZ!r}, got {tz!r}")
    moment = zoned(local, CAIRO_TZ)
    weekday = spec.get("weekday")
    if weekday is not None and weekday != weekday_name(moment):
        raise ValueError(f"now.weekday {weekday!r} but {local} is a {weekday_name(moment)}")
    offset = spec.get("offset")
    if offset is not None and offset != offset_str(moment):
        raise ValueError(f"now.offset {offset!r} but {local} in {CAIRO_TZ} is {offset_str(moment)}")
    return moment


def render_now(moment: datetime) -> dict[str, str]:
    """The `now` block with the offset rendered from the zone (DST-correct)."""
    local = moment.astimezone(CAIRO)
    return {
        "local": local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "tz": CAIRO_TZ,
        "weekday": weekday_name(local),
        "offset": offset_str(local),
        "iso": local.isoformat(timespec="seconds"),
    }


def _last_weekday_of(year: int, month: int, weekday: int) -> date:
    last = date(year, month, _calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def egypt_dst_period(year: int) -> tuple[date, date]:
    """First and last local dates on summer time by the rule in force since 2023.

    Summer time starts at 00:00 on the last Friday of April and ends at 24:00 on the last
    Thursday of October, so both returned dates are (at least partly) on UTC+3.
    """
    return _last_weekday_of(year, 4, 4), _last_weekday_of(year, 10, 3)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def resolve_date(spec: str, now: DateLike) -> date:
    """Resolve a relative-date spec (see the module docstring) against `now`."""
    today = as_date(now)
    if _DATE_RE.fullmatch(spec):
        return parse_date(spec)
    if spec == "today":
        return today
    if m := _DAYS_SPEC.fullmatch(spec):
        days = int(m.group(2))
        return today + timedelta(days=days if m.group(1) == "+" else -days)
    if m := _WEEKDAY_SPEC.fullmatch(spec):
        ahead = (WEEKDAYS.index(m.group(2)) - today.weekday()) % 7
        if m.group(1) == "next" and ahead == 0:
            ahead = 7
        return today + timedelta(days=ahead)
    if m := _MONTH_SPEC.fullmatch(spec):
        year, month = _shift_month(today.year, today.month, int(m.group(1)))
        last = _calendar.monthrange(year, month)[1]
        day = last if m.group(2) == "last" else int(m.group(2))
        if not 1 <= day <= last:
            raise ValueError(f"day {day} does not exist in {year}-{month:02d}: {spec!r}")
        return date(year, month, day)
    raise ValueError(f"unknown relative-date spec: {spec!r}")


def resolve(spec: str, now: DateLike) -> str:
    """Resolve a relative-date spec to an ISO date string."""
    return resolve_date(spec, now).isoformat()
