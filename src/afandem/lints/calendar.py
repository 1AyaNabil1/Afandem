"""Calendar lint (docs/dataset-spec.md §2 lint table, §3 date tags, §4 Calendars).

Scenario-level and clinic only: banking and telecom have no calendar-gated tool and so no
calendar, and the lint returns nothing for them. The calendar is read through the sandbox's
`ClinicCalendar`; one that does not load is the `state` lint's finding, not this one's.

- Expected writes: every `date` argument of an expected tool call (each acceptable value) falls
  on an open day, and with a `time` argument every date and time pair is inside the opening
  hours. The sandbox refuses anything else, so such a gold can never be reached: error.
- Resolved dates in the slot table (a slot holding an ISO date): an open day and not a holiday,
  unless the item is about that. `ask` items and list golds (a list-valued date slot or a list of
  acceptable expected dates) are; otherwise a closed date is an error on an `act` item and a
  warning on the behaviours that write nothing (no gold date to be unfair about).
- `date_relative_weekday`: the target, `days_ahead` days after `now` (or the only single-date
  slot), is 2-5 days ahead; outside that the gold is a list or the item `ask` (1 day ahead
  competes with 'tomorrow', 6-7 with 'next week'). Same exemptions and severities.
- `date_hijri_ramadan`: the calendar is flagged `ramadan` and `now` falls inside its
  `ramadan_from`..`ramadan_to` (errors); without both bounds the lint cannot tell (manual).
- The calendar's `holidays` list Egypt's fixed-date public holidays for the year of `now` and of
  every resolved date (warning), so a date on one of them cannot pass as open.

The weekday written next to each resolved date is checked by `slot_dates`.
"""

import datetime as dt
from collections.abc import Iterator

from pydantic import ValidationError

from afandem.lints.findings import Finding, Severity
from afandem.lints.slots import TIME_RE, date_slots, iso_date
from afandem.sandbox.calendar import (
    ClinicCalendar,
    closure,
    in_ramadan,
    is_holiday,
    is_open_day,
    missing_fixed_holidays,
)
from afandem.scenarios.schema import WEEKDAYS, Scenario, ToolCall

RULE = "calendar"
CALENDAR_DOMAINS = frozenset({"clinic"})
RELATIVE_WEEKDAY_TAG = "date_relative_weekday"
RAMADAN_TAG = "date_hijri_ramadan"
RELATIVE_WEEKDAY_DAYS = range(2, 6)
"""How far ahead a relative-weekday target may be for one gold date (2-5 days)."""


def _day(day: dt.date) -> str:
    return f"{day.isoformat()} ({WEEKDAYS[day.weekday()]})"


def _is_date_key(key: str) -> bool:
    return key == "date" or key.endswith("_date")


def _is_time_key(key: str) -> bool:
    return key == "time" or key.endswith("_time")


def _strings(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str)]


def _call_dates(call: ToolCall) -> Iterator[tuple[dt.date, bool]]:
    """(date, part of a list of acceptable values) for every date argument of a call."""
    for key, value in call.args.items():
        if _is_date_key(key):
            listed = isinstance(value, list) and len(value) > 1
            for item in _strings(value):
                if (day := iso_date(item)) is not None:
                    yield day, listed


def closed_reason(calendar: ClinicCalendar, day: dt.date) -> str | None:
    """Why the clinic is closed all day on `day` (a holiday, a closed weekday), else None."""
    if is_holiday(calendar, day):
        return "a holiday in the calendar"
    if not is_open_day(calendar, day):
        return f"a closed day ({WEEKDAYS[day.weekday()]})"
    return None


def _list_gold(scenario: Scenario) -> bool:
    """The item resolves its date to several acceptable values (a list-valued date slot, or a
    list in an expected date argument)."""
    if any(len(parsed) > 1 for parsed in date_slots(scenario.slots).values()):
        return True
    return any(listed for call in scenario.expected.tool_calls for _, listed in _call_dates(call))


def _gold_severity(scenario: Scenario) -> Severity | None:
    """None when the item may be about a closed day or a far date (`ask`); an error on `act`
    items, whose gold date it is; a warning on the behaviours that write nothing."""
    if scenario.behaviour == "ask":
        return None
    return "error" if scenario.behaviour == "act" else "warning"


def _expected_findings(scenario: Scenario, calendar: ClinicCalendar) -> list[Finding]:
    findings: list[Finding] = []
    for call in scenario.expected.tool_calls:
        times = [
            item
            for key, value in call.args.items()
            if _is_time_key(key)
            for item in _strings(value)
            if TIME_RE.match(item)
        ]
        for day, _ in _call_dates(call):
            if (reason := closed_reason(calendar, day)) is not None:
                message = (
                    f"expected {call.name} date {_day(day)} is {reason}: the sandbox refuses "
                    "it, so this gold can never be reached"
                )
                findings.append(Finding(RULE, message, field="expected"))
                continue
            for hhmm in times:
                if closure(calendar, day, hhmm) is not None:
                    message = (
                        f"expected {call.name} at {_day(day)} {hhmm} is outside the clinic's "
                        "opening hours: the sandbox refuses it"
                    )
                    findings.append(Finding(RULE, message, field="expected"))
    return findings


def _slot_findings(scenario: Scenario, calendar: ClinicCalendar) -> list[Finding]:
    severity = _gold_severity(scenario)
    if severity is None or _list_gold(scenario):
        return []
    findings: list[Finding] = []
    for key, parsed in date_slots(scenario.slots).items():
        (day,) = parsed  # a slot with several dates makes a list gold, handled above
        if (reason := closed_reason(calendar, day)) is not None:
            message = (
                f"slot {key!r} = {_day(day)} is {reason}; an item about a closed day is "
                "`ask` or has a list gold"
            )
            findings.append(Finding(RULE, message, field="slots", severity=severity))
    return findings


def _relative_weekday_findings(scenario: Scenario) -> list[Finding]:
    if RELATIVE_WEEKDAY_TAG not in scenario.phenomena:
        return []
    severity = _gold_severity(scenario)
    if severity is None or _list_gold(scenario):
        return []
    slots = scenario.slots
    singles = {key: parsed[0] for key, parsed in date_slots(slots).items()}
    days_ahead = slots.get("days_ahead")
    if isinstance(days_ahead, int) and not isinstance(days_ahead, bool):
        distance, source = days_ahead, "days_ahead"
    elif len(singles) == 1:
        ((key, day),) = singles.items()
        distance, source = (day - scenario.now.local_date).days, f"slot {key!r}"
    elif not singles:
        message = f"tagged {RELATIVE_WEEKDAY_TAG} but the slot table resolves no date"
        return [Finding(RULE, message, field="slots", severity="warning")]
    else:
        message = (
            f"tagged {RELATIVE_WEEKDAY_TAG} with several dates ({', '.join(singles)}) and no "
            "days_ahead: set days_ahead to the target's distance from now"
        )
        return [Finding(RULE, message, field="slots", severity="manual")]
    if distance in RELATIVE_WEEKDAY_DAYS:
        return []
    message = (
        f"the relative-weekday target is {distance} day(s) after now ({source}); outside "
        f"{RELATIVE_WEEKDAY_DAYS.start}-{RELATIVE_WEEKDAY_DAYS.stop - 1} days ahead the gold is "
        "a list or the item `ask`"
    )
    return [Finding(RULE, message, field="slots", severity=severity)]


def _ramadan_findings(scenario: Scenario, calendar: ClinicCalendar) -> list[Finding]:
    if RAMADAN_TAG not in scenario.phenomena:
        return []
    if not calendar.ramadan:
        message = f"tagged {RAMADAN_TAG} but the calendar is not a Ramadan calendar (ramadan)"
        return [Finding(RULE, message, field="initial_state")]
    start, end = calendar.ramadan_from, calendar.ramadan_to
    if start is None or end is None:
        message = (
            f"{RAMADAN_TAG}: give the calendar ramadan_from and ramadan_to (verified against "
            "Dar al-Ifta) so the lint can check that now falls in Ramadan"
        )
        return [Finding(RULE, message, field="initial_state", severity="manual")]
    now = scenario.now.local_date
    if not in_ramadan(calendar, now):
        message = f"{RAMADAN_TAG}: now ({_day(now)}) is outside Ramadan ({start} to {end})"
        return [Finding(RULE, message, field="now")]
    return []


def _holiday_findings(scenario: Scenario, calendar: ClinicCalendar) -> list[Finding]:
    years = {scenario.now.local_date.year}
    years.update(day.year for parsed in date_slots(scenario.slots).values() for day in parsed)
    years.update(day.year for call in scenario.expected.tool_calls for day, _ in _call_dates(call))
    findings: list[Finding] = []
    for year in sorted(years):
        missing = missing_fixed_holidays(calendar, year)
        if missing:
            message = (
                f"calendar.holidays leaves out Egypt's fixed-date public holidays of {year}: "
                f"{', '.join(missing)}"
            )
            findings.append(Finding(RULE, message, field="initial_state", severity="warning"))
    return findings


def check_calendar(scenario: Scenario) -> list[Finding]:
    if scenario.domain not in CALENDAR_DOMAINS:
        return []
    try:
        calendar = ClinicCalendar.model_validate(scenario.initial_state.get("calendar"))
    except ValidationError:
        return []  # the state lint reports a calendar that does not load
    return [
        *_expected_findings(scenario, calendar),
        *_slot_findings(scenario, calendar),
        *_relative_weekday_findings(scenario),
        *_ramadan_findings(scenario, calendar),
        *_holiday_findings(scenario, calendar),
    ]
