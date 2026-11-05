"""The calendar lint, on the spec example (`now` Wednesday 4 Nov 2026, gold Sunday 8 Nov, clinic
closed on Fridays). Texts are untouched or `<column ...>` placeholders."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_calendar
from afandem.scenarios import COLUMNS, Scenario

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "scenarios" / "clinic" / "clinic-0042.json"
BANKING = FIXTURES / "smoke" / "banking" / "banking-9001.json"
FRIDAY, SATURDAY, THURSDAY = "2026-11-06", "2026-11-07", "2026-11-05"


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def example() -> dict[str, Any]:
    return load(EXAMPLE)


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_calendar(Scenario.model_validate(doc))


def summary(findings: list[Finding]) -> list[tuple[str, str | None, str]]:
    return [(f.rule, f.field, f.severity) for f in findings]


def move_to(doc: dict[str, Any], day: str, weekday: str, days_ahead: int) -> dict[str, Any]:
    """The example rescheduled to another day (slot table and expected call)."""
    doc["slots"].update(new_date=day, new_date_weekday=weekday, days_ahead=days_ahead)
    doc["expected"]["tool_calls"][0]["args"]["date"] = day
    return doc


def as_none(doc: dict[str, Any]) -> dict[str, Any]:
    doc["behaviour"] = "none"
    doc["expected"].update(tool_calls=[], end_state_patch={})
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
    return doc


def as_ask(doc: dict[str, Any]) -> dict[str, Any]:
    doc["behaviour"] = "ask"
    doc["expected"]["expected_clarification"] = "new_date"
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
        doc["texts"][name]["follow_up"] = f"<{name} follow_up>"
    return doc


def test_the_spec_example_is_clean() -> None:
    assert lint(example()) == []


def test_banking_has_no_calendar_and_is_skipped() -> None:
    doc = load(BANKING)
    doc["phenomena"] = ["date_relative_weekday", "date_hijri_ramadan"]
    doc["slots"].update(date=FRIDAY, days_ahead=9)
    assert lint(doc) == []


def test_a_calendar_that_does_not_load_is_left_to_the_state_lint() -> None:
    doc = example()
    doc["initial_state"]["calendar"] = {"closed": "Fri"}
    assert lint(doc) == []


def test_an_act_gold_on_a_closed_day() -> None:
    findings = lint(move_to(example(), FRIDAY, "Friday", 2))
    assert summary(findings) == [
        ("calendar", "expected", "error"),
        ("calendar", "slots", "error"),
    ]
    assert "reschedule_appointment date 2026-11-06 (Friday) is a closed day" in findings[0].message
    assert "slot 'new_date' = 2026-11-06 (Friday) is a closed day" in findings[1].message


def test_an_act_gold_on_a_holiday() -> None:
    doc = example()
    doc["initial_state"]["calendar"]["holidays"].append("2026-11-08")
    findings = lint(doc)
    assert summary(findings) == [("calendar", "expected", "error"), ("calendar", "slots", "error")]
    assert all("a holiday in the calendar" in f.message for f in findings)


def test_an_expected_time_outside_the_opening_hours() -> None:
    doc = example()
    doc["expected"]["tool_calls"][0]["args"]["time"] = ["15:30", "23:00"]
    findings = lint(doc)
    assert summary(findings) == [("calendar", "expected", "error")]
    assert "2026-11-08 (Sunday) 23:00 is outside the clinic's opening hours" in findings[0].message


def test_every_acceptable_expected_date_must_be_open() -> None:
    doc = example()
    doc["expected"]["tool_calls"][0]["args"]["date"] = ["2026-11-08", FRIDAY]
    findings = lint(doc)
    assert summary(findings) == [("calendar", "expected", "error")]
    assert FRIDAY in findings[0].message


def test_a_closed_day_the_item_is_about_passes() -> None:
    listed = example()
    listed["slots"].update(new_date=FRIDAY, new_date_weekday="Friday", days_ahead=2)
    listed["expected"]["tool_calls"][0]["args"]["date"] = [THURSDAY, SATURDAY]
    assert lint(listed) == []
    asked = as_ask(example())
    asked["slots"].update(new_date=FRIDAY, new_date_weekday="Friday", days_ahead=2)
    asked["expected"]["tool_calls"][0]["args"]["date"] = SATURDAY
    assert lint(asked) == []
    window = example()
    window["slots"]["window"] = [FRIDAY, SATURDAY]
    assert lint(window) == []


def test_a_closed_day_on_an_item_that_writes_nothing_is_a_warning() -> None:
    findings = lint(as_none(move_to(example(), FRIDAY, "Friday", 2)))
    assert summary(findings) == [("calendar", "slots", "warning")]


@pytest.mark.parametrize(
    ("day", "weekday", "days_ahead"),
    [(THURSDAY, "Thursday", 1), ("2026-11-10", "Tuesday", 6), ("2026-11-11", "Wednesday", 7)],
)
def test_relative_weekday_target_outside_two_to_five_days(
    day: str, weekday: str, days_ahead: int
) -> None:
    findings = lint(move_to(example(), day, weekday, days_ahead))
    assert summary(findings) == [("calendar", "slots", "error")]
    assert f"target is {days_ahead} day(s) after now (days_ahead)" in findings[0].message
    assert "2-5 days ahead" in findings[0].message


@pytest.mark.parametrize(("day", "weekday", "days_ahead"), [(SATURDAY, "Saturday", 3)])
def test_relative_weekday_target_inside_two_to_five_days(
    day: str, weekday: str, days_ahead: int
) -> None:
    assert lint(move_to(example(), day, weekday, days_ahead)) == []


def test_relative_weekday_exemptions_and_severities() -> None:
    far = ("2026-11-10", "Tuesday", 6)
    listed = move_to(example(), *far)
    listed["expected"]["tool_calls"][0]["args"]["date"] = ["2026-11-10", "2026-11-17"]
    assert lint(listed) == []
    asked = as_ask(move_to(example(), *far))
    assert lint(asked) == []
    untagged = move_to(example(), *far)
    untagged["phenomena"].remove("date_relative_weekday")
    assert lint(untagged) == []
    assert summary(lint(as_none(move_to(example(), *far)))) == [("calendar", "slots", "warning")]


def test_relative_weekday_target_from_the_only_date_slot() -> None:
    doc = move_to(example(), "2026-11-11", "Wednesday", 7)
    del doc["slots"]["days_ahead"]
    findings = lint(doc)
    assert summary(findings) == [("calendar", "slots", "error")]
    assert "7 day(s) after now (slot 'new_date')" in findings[0].message


def test_relative_weekday_target_that_cannot_be_told() -> None:
    several = example()
    del several["slots"]["days_ahead"]
    several["slots"].update(other_date=SATURDAY, other_date_weekday="Saturday")
    assert summary(lint(several)) == [("calendar", "slots", "manual")]
    none = example()
    for key in ("new_date", "new_date_weekday", "days_ahead"):
        del none["slots"][key]
    findings = lint(none)
    assert summary(findings) == [("calendar", "slots", "warning")]
    assert "resolves no date" in findings[0].message


AFTERNOON = [{"open": "13:00", "close": "17:00"}]  # covers the example's 15:30


def ramadan(doc: dict[str, Any], **calendar: object) -> dict[str, Any]:
    doc["phenomena"].append("date_hijri_ramadan")
    doc["initial_state"]["calendar"].update(calendar)
    return doc


def test_hijri_items_need_a_ramadan_calendar_and_a_ramadan_now() -> None:
    no_calendar = lint(ramadan(example()))
    assert summary(no_calendar) == [("calendar", "initial_state", "error")]
    assert "not a Ramadan calendar" in no_calendar[0].message
    unbounded = lint(ramadan(example(), ramadan=True, ramadan_hours=AFTERNOON))
    assert summary(unbounded) == [("calendar", "initial_state", "manual")]
    assert "ramadan_from and ramadan_to" in unbounded[0].message
    outside = ramadan(example(), ramadan=True, ramadan_from="2026-11-10", ramadan_to="2026-12-09")
    findings = lint(outside)
    assert summary(findings) == [("calendar", "now", "error")]
    assert "now (2026-11-04 (Wednesday)) is outside Ramadan" in findings[0].message
    inside = ramadan(example(), ramadan=True, ramadan_from="2026-11-01", ramadan_to="2026-11-30")
    in_hours = lint(inside)  # the default Ramadan hours (21:00-01:00) miss the 15:30 gold
    assert summary(in_hours) == [("calendar", "expected", "error")]
    inside["initial_state"]["calendar"]["ramadan_hours"] = AFTERNOON
    assert lint(inside) == []


def test_the_fixed_date_public_holidays_of_every_year_used() -> None:
    doc = example()
    doc["initial_state"]["calendar"]["holidays"].remove("2026-10-06")
    findings = lint(doc)
    assert summary(findings) == [("calendar", "initial_state", "warning")]
    assert "of 2026: 2026-10-06" in findings[0].message
    next_year = example()
    next_year["slots"].update(other_date="2027-01-03", other_date_weekday="Sunday")
    findings = lint(next_year)
    assert summary(findings) == [("calendar", "initial_state", "warning")]
    assert "of 2027: 2027-01-07, 2027-01-25" in findings[0].message
