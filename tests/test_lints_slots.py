"""Slot re-extraction and slot dates. Surface forms are quoted from docs/dataset-spec.md;
other texts are `<column text>` placeholders."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, lint_scenario
from afandem.lints.slots import (
    ColumnView,
    check_slot_dates,
    check_slots,
    date_found,
    integer_found,
    phone_found,
    time_found,
    weekday_found,
)
from afandem.scenarios import COLUMNS, Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"
NOW = dt.date(2026, 11, 4)  # the example's Wednesday
SUNDAY = dt.date(2026, 11, 8)


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_slots(Scenario.model_validate(doc))


def view(text: str) -> ColumnView:
    return ColumnView.of("x", text)


def test_spec_example_needs_only_manual_checks() -> None:
    findings = lint(example())
    assert {f.severity for f in findings} == {"manual"}
    assert [f.message.split(": ")[0] for f in findings] == [
        "slot 'intent' = 'reschedule'",
        "slot 'new_time' = '15:30'",
    ]


def test_missing_date_is_an_error_in_that_column() -> None:
    doc = example()
    doc["texts"]["egy"]["text"] = "<egy text>"
    errors = [f for f in lint(doc) if f.severity == "error"]
    assert [(f.rule, f.column) for f in errors] == [("slot_reextraction", "egy")]
    assert "'new_date'" in errors[0].message


def test_the_variant_text_is_checked_too() -> None:
    doc = example()
    doc["arabizi_variant"]["text"] = "<variant text>"
    errors = [f for f in lint(doc) if f.severity == "error"]
    assert [f.column for f in errors] == ["arabizi_variant"]


def test_follow_up_counts_for_ask_items() -> None:
    doc = example()
    doc["behaviour"] = "ask"
    doc["expected"]["expected_clarification"] = "new_date"
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
        doc["texts"][name]["follow_up"] = f"<{name} follow_up>"
    doc["texts"]["egy"]["text"] = "<egy text>"
    doc["texts"]["egy"]["follow_up"] = "الحد"
    assert not [f for f in lint(doc) if f.severity == "error"]


@pytest.mark.parametrize(
    "text", ["الحد", "الأحد", "للحد", "يوم الأحد", "Sunday", "el 7ad", "lel 7ad", "ll 7ad"]
)
def test_weekday_forms(text: str) -> None:
    assert weekday_found("Sunday", view(text))


@pytest.mark.parametrize("text", ["7ad", "<egy text>", "Saturday", "السبت"])
def test_weekday_non_forms(text: str) -> None:
    assert not weekday_found("Sunday", view(text))


@pytest.mark.parametrize(
    ("days", "text", "expected"),
    [
        (1, "بكرة", True),
        (1, "bokra", True),
        (1, "tomorrow", True),
        (1, "الغد", True),
        (1, "غداً", True),
        (2, "بعد بكرة", True),
        (2, "ba3d bokra", True),
        (1, "بعد بكرة", False),
        (1, "ba3d bokra", False),
        (2, "بكرة", False),
        (2, "بعد غد", True),
        (2, "بعد غدٍ", True),
        (2, "بعد الغد", True),
        (2, "the day after tomorrow", True),
        (2, "The day after tomorrow", True),
        (1, "بعد غد", False),
        (1, "بعد الغد", False),
        (1, "the day after tomorrow", False),
    ],
)
def test_relative_days_count_from_now(days: int, text: str, expected: bool) -> None:
    assert date_found(NOW + dt.timedelta(days=days), view(text), NOW) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("٨/١١", True),
        ("8/11", True),
        ("8/11/2026", True),
        ("٨ نوفمبر", True),
        ("٨ شهر ١١", True),
        ("8 Nov", True),
        ("Nov 8", True),
        ("يوم ٨", True),
        ("8/12", False),
        ("18/11", False),
        ("8/11/2025", False),
    ],
)
def test_numeric_dates(text: str, expected: bool) -> None:
    assert date_found(SUNDAY, view(text), NOW) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("٠١٠٠٠٠٠٠٠١٧", True),
        ("01000000017", True),
        ("010 0000 0017", True),
        ("0100-000-0017", True),
        ("+20 10 0000 0017", True),
        ("0020 1000000017", True),
        ("+201000000017", True),
        ("1000000017", False),
        ("01000000018", False),
    ],
)
def test_phone_forms(text: str, expected: bool) -> None:
    assert phone_found("1000000017", view(text)) is expected


def test_missing_phone_is_an_error() -> None:
    doc = example()
    doc["slots"]["phone"] = "+201000000017"
    assert not [f for f in lint(doc) if f.severity == "error"]
    doc["texts"]["cs"]["text"] = "<cs text>"
    errors = [f for f in lint(doc) if f.severity == "error"]
    assert {(f.column, f.message.split(": ")[0]) for f in errors} == {
        ("cs", "slot 'new_date' = '2026-11-08'"),
        ("cs", "slot 'phone' = '+201000000017'"),
    }


@pytest.mark.parametrize(
    ("value", "text", "expected"),
    [
        (1250, "ألف وربع", True),
        (1250, "alf w rob3", True),
        (1250, "one thousand two hundred and fifty", True),
        (1250, "ألف وميتين وخمسين", True),
        (1500, "١٬٥٠٠", True),
        (1500, "1.500", True),
        (1500, "1,500", True),
        (2000, "2k", True),
        (350, "تلتميت وخمسين", True),
        (300, "تلتميت وخمسين", False),
        (300, "تلتميت", True),
        (50, "شحن ٥٠", True),
        (500, "<egy text>", False),
    ],
)
def test_integers(value: int, text: str, expected: bool) -> None:
    assert integer_found(value, view(text)) is expected


def test_unfound_integer_is_manual_not_an_error() -> None:
    doc = example()
    doc["slots"]["amount_egp"] = 1250
    amount = [f for f in lint(doc) if "'amount_egp'" in f.message]
    assert [(f.severity, f.column) for f in amount] == [("manual", None)]
    assert "en, msa, egy, arabizi, cs, cs_latin, arabizi_variant" in amount[0].message


@pytest.mark.parametrize(
    ("text", "expected"),
    [("15:30", True), ("3:30", True), ("٣:٣٠", True), ("3:31", False), ("4:30", False)],
)
def test_times(text: str, expected: bool) -> None:
    assert time_found("15:30", view(text)) is expected


def test_ids_resolve_through_aliases() -> None:
    doc = example()
    doc["slots"]["doctor_id"] = "d_2"
    doctor = [f for f in lint(doc) if "'doctor_id'" in f.message]
    assert doctor[0].severity == "manual"
    assert "egy" in doctor[0].message
    doc["texts"]["egy"]["text"] = "الدكتورة هبة"
    doc["texts"]["en"]["text"] = "Dr. Heba El Sayed"
    doctor = [f for f in lint(doc) if "'doctor_id'" in f.message]
    assert "egy" not in doctor[0].message.split("in ")[1]
    assert "en," not in doctor[0].message


def test_principal_ids_need_not_be_said() -> None:
    doc = example()
    doc["texts"]["en"]["text"] = "<en text> Sunday"
    assert not [f for f in lint(doc) if "patient_id" in f.message]


def test_list_valued_slots_are_manual_when_not_found() -> None:
    doc = example()
    doc["slots"]["window"] = ["2026-12-01", "2026-12-02"]
    window = [f for f in lint(doc) if "'window'" in f.message]
    assert [f.severity for f in window] == ["manual"]


def test_slot_dates_clean_on_the_example() -> None:
    assert check_slot_dates(Scenario.model_validate(example())) == []


@pytest.mark.parametrize(
    ("change", "severity", "message"),
    [
        ({"new_date_weekday": "Monday"}, "error", "'new_date' is 'Sunday'"),
        ({"days_ahead": 5}, "error", "days_ahead is 5 but the date is 4 days after now"),
        ({"new_time_weekday": "Sunday"}, "error", "which is not a date"),
        ({"other_date": "2026-11-09"}, "warning", "has no 'other_date_weekday'"),
        ({"other_date": "2026-02-30"}, "error", "2026-02-30 is not a calendar date"),
        ({"other_date": ["2026-11-09", "2026-13-01"]}, "error", "2026-13-01 is not a calendar"),
    ],
)
def test_slot_dates(change: dict[str, Any], severity: str, message: str) -> None:
    doc = example()
    doc["slots"].update(change)
    findings = check_slot_dates(Scenario.model_validate(doc))
    assert [(f.rule, f.severity) for f in findings] == [("slot_dates", severity)]
    assert message in findings[0].message


def test_an_impossible_date_is_a_finding_not_a_crash() -> None:
    doc = example()
    doc["slots"]["new_date"] = "2026-02-30"
    findings = lint_scenario(Scenario.model_validate(doc))
    assert ("slot_dates", "error") in {(f.rule, f.severity) for f in findings}
    assert any(f.severity == "manual" and "'new_date'" in f.message for f in findings)


def test_slot_dates_accept_lists() -> None:
    doc = example()
    doc["slots"]["window"] = ["2026-12-01", "2026-12-02"]
    doc["slots"]["window_weekday"] = ["Tuesday", "Wednesday"]
    assert check_slot_dates(Scenario.model_validate(doc)) == []
