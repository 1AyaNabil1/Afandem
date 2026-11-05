"""Opening calendars, stored in scenario state (never in the harness).

Clinic: closed weekdays (Friday), regular hours (evening or split sessions), Ramadan hours when
the calendar is flagged, and the closure dates for the `now` year (the Egyptian fixed-date public
holidays plus the Eid and other movable dates) listed in `holidays`. The state's list is
authoritative; `fixed_holidays` and `missing_fixed_holidays` help authors and lints check it.
Banking has no calendar-gated tool, so it has no calendar.

Hours are half-open `[open, close)`. A session whose `close` is not after its `open`
(`21:00-01:00`, or `22:00-00:00` for "until midnight") runs past midnight; its after-midnight
part belongs to the next calendar date, and is open only if the session's own day is.
"""

from datetime import date, timedelta
from typing import Literal, Self

from pydantic import Field, model_validator

from afandem.sandbox.clock import DateLike, as_date, parse_date, weekday_code
from afandem.sandbox.fields import Hhmm, IsoDate, StateModel, Weekday

type Closure = Literal["closed_day", "outside_hours"]

# Egypt's fixed-date public holidays (month, day): Coptic Christmas, 25 January, Sinai
# Liberation Day, Labour Day, 30 June, Revolution Day, Armed Forces Day. The movable ones
# (Sham el-Nessim, both Eids, Islamic New Year, the Prophet's Birthday) are authored per year.
FIXED_HOLIDAYS: tuple[tuple[int, int], ...] = (
    (1, 7),
    (1, 25),
    (4, 25),
    (5, 1),
    (6, 30),
    (7, 23),
    (10, 6),
)


class Hours(StateModel):
    open: Hhmm
    close: Hhmm


def _ramadan_default() -> list[Hours]:
    return [Hours(open="21:00", close="01:00")]


class ClinicCalendar(StateModel):
    closed: list[Weekday]
    hours: list[Hours] = Field(min_length=1)
    ramadan: bool = False
    ramadan_from: IsoDate | None = None
    ramadan_to: IsoDate | None = None
    ramadan_hours: list[Hours] = Field(default_factory=_ramadan_default, min_length=1)
    holidays: list[IsoDate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ramadan_bounds(self) -> Self:
        if (
            self.ramadan_from is not None
            and self.ramadan_to is not None
            and parse_date(self.ramadan_from) > parse_date(self.ramadan_to)
        ):
            raise ValueError("ramadan_from is after ramadan_to")
        return self


def fixed_holidays(year: int) -> list[str]:
    """Egypt's fixed-date public holidays in `year`, as ISO dates."""
    return [date(year, month, day).isoformat() for month, day in FIXED_HOLIDAYS]


def missing_fixed_holidays(calendar: ClinicCalendar, year: int) -> list[str]:
    """Fixed-date holidays of `year` that the calendar's `holidays` list leaves out."""
    listed = {parse_date(d) for d in calendar.holidays}
    return [d for d in fixed_holidays(year) if parse_date(d) not in listed]


def is_holiday(calendar: ClinicCalendar, day: DateLike) -> bool:
    target = as_date(day)
    return any(parse_date(d) == target for d in calendar.holidays)


def is_open_day(calendar: ClinicCalendar, day: DateLike) -> bool:
    """Not a closed weekday and not a listed holiday."""
    target = as_date(day)
    return weekday_code(target).capitalize() not in calendar.closed and not is_holiday(
        calendar, target
    )


def in_ramadan(calendar: ClinicCalendar, day: DateLike) -> bool:
    """Ramadan hours apply: the calendar is flagged and the date is inside the optional bounds."""
    if not calendar.ramadan:
        return False
    target = as_date(day)
    if calendar.ramadan_from is not None and target < parse_date(calendar.ramadan_from):
        return False
    return calendar.ramadan_to is None or target <= parse_date(calendar.ramadan_to)


def hours_for(calendar: ClinicCalendar, day: DateLike) -> list[Hours]:
    return calendar.ramadan_hours if in_ramadan(calendar, day) else calendar.hours


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _covers(session: Hours, minute: int, *, own_day: bool) -> bool:
    start, end = _minutes(session.open), _minutes(session.close)
    if end > start:
        return own_day and start <= minute < end
    return start <= minute if own_day else minute < end


def is_open(calendar: ClinicCalendar, day: DateLike, at: str) -> bool:
    """Is the clinic open at local time `at` (HH:MM) on `day`?"""
    target, minute = as_date(day), _minutes(at)
    if is_open_day(calendar, target) and any(
        _covers(s, minute, own_day=True) for s in hours_for(calendar, target)
    ):
        return True
    previous = target - timedelta(days=1)
    return is_open_day(calendar, previous) and any(
        _covers(s, minute, own_day=False) for s in hours_for(calendar, previous)
    )


def closure(calendar: ClinicCalendar, day: DateLike, at: str) -> Closure | None:
    """`None` when open; else `closed_day` (closed weekday or holiday) or `outside_hours`."""
    if is_open(calendar, day, at):
        return None
    return "outside_hours" if is_open_day(calendar, day) else "closed_day"
