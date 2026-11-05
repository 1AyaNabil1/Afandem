"""Normalisers v1, driven by the JSON tables in tests/fixtures/normalisers/ (harness-spec §8, §12).

The tables grow while authoring; each row is one input and its normalised value.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from afandem.scoring import normalise as n

TABLES = Path(__file__).parent / "fixtures" / "normalisers"


def rows(name: str, key: str = "cases") -> list[dict[str, Any]]:
    table: dict[str, Any] = json.loads((TABLES / f"{name}.json").read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = table[key]
    return cases


def ids(cases: list[dict[str, Any]], field: str = "input") -> list[str]:
    return [str(case.get(field, case.get("text"))) for case in cases]


NOW = dt.date.fromisoformat(json.loads((TABLES / "dates.json").read_text(encoding="utf-8"))["now"])


def test_version() -> None:
    assert n.NORMALISER_VERSION == "1"


@pytest.mark.parametrize("case", rows("digits"), ids=ids(rows("digits")))
def test_digits_and_marks(case: dict[str, Any]) -> None:
    assert n.has_non_ascii_digits(case["input"]) is case["non_ascii_digits"]
    assert n.clean(case["input"]) == case["clean"]


@pytest.mark.parametrize("case", rows("numbers"), ids=ids(rows("numbers")))
def test_numbers(case: dict[str, Any]) -> None:
    assert n.parse_number(case["input"]) == case["value"]


@pytest.mark.parametrize("case", rows("money"), ids=ids(rows("money")))
def test_money(case: dict[str, Any]) -> None:
    assert n.parse_money(case["input"]) == case["egp"]


@pytest.mark.parametrize("case", rows("money", "currency"), ids=ids(rows("money", "currency")))
def test_currency_markers(case: dict[str, Any]) -> None:
    assert n.has_currency(case["input"]) is case["has_currency"]


@pytest.mark.parametrize("case", rows("times"), ids=ids(rows("times")))
def test_times(case: dict[str, Any]) -> None:
    hours = [tuple(pair) for pair in case["hours"]] if case["hours"] else None
    assert n.parse_time(case["input"], hours) == case["time"]


@pytest.mark.parametrize("case", rows("times", "windows"), ids=ids(rows("times", "windows")))
def test_period_windows(case: dict[str, Any]) -> None:
    window = n.period_window(case["input"])
    assert (list(window) if window else None) == case["window"]


@pytest.mark.parametrize("case", rows("dates"), ids=ids(rows("dates")))
def test_dates_are_dates(case: dict[str, Any]) -> None:
    parsed = n.parse_date(case["input"], NOW)
    assert (parsed.isoformat() if parsed else None) == case["date"]


def test_find_dates_reads_every_form_once() -> None:
    found = n.find_dates("8/11, ٨ نوفمبر, 2026-11-08 and 23/11/2026", NOW)
    assert found == [dt.date(2026, 11, 8), dt.date(2026, 11, 23)]


@pytest.mark.parametrize("case", rows("phones"), ids=ids(rows("phones")))
def test_phones(case: dict[str, Any]) -> None:
    phone = n.normalise_phone_value(case["input"])
    assert phone.e164 == case["e164"]
    assert list(phone.flags) == case["flags"]


def test_find_phones_in_a_reply() -> None:
    assert n.find_phones("[reply] 010 0000 0017 / ٠١٥٠٠٠٠١٤١٤ / 0223456789") == [
        "+201000000017",
        "+201500001414",
    ]


@pytest.mark.parametrize("case", rows("forms", "cases"), ids=ids(rows("forms", "cases"), "text"))
def test_folding_and_whole_word_forms(case: dict[str, Any]) -> None:
    assert n.contains_form(n.text_tokens(case["text"]), case["form"]) is case["match"]


@pytest.mark.parametrize(
    "case", rows("forms", "answers"), ids=ids(rows("forms", "answers"), "text")
)
def test_inform_answers(case: dict[str, Any]) -> None:
    hours = [("10:00", "22:00")]
    found = n.answer_found(case["text"], case["value"], case["forms"], now=NOW, hours=hours)
    assert found is case["match"]


@pytest.mark.parametrize(
    "case", rows("args"), ids=[f"{c['field']}={c['actual']}" for c in rows("args")]
)
def test_argument_matching(case: dict[str, Any]) -> None:
    assert n.arg_matches(case["field"], case["actual"], case["wanted"]) is case["match"]


def test_normalised_args_recurse_and_keep_types() -> None:
    args = {"date": "2026-11-08", "nested": {"phone": "01000000017"}, "ids": ["a_1"], "n": 2.0}
    assert n.normalised_args(args) == {
        "date": "2026-11-08",
        "nested": {"phone": "+201000000017"},
        "ids": ["a_1"],
        "n": 2,
    }
    assert n.normalise_arg("x", None) is None
    assert n.normalise_arg("date", "not a date") == "not a date"
    assert n.normalise_arg("amount_egp", "<no amount>") == "<no amount>"
    assert n.normalise_arg("x", 1.5) == 1.5
    assert n.normalise_arg("x", object) is object


def test_fold_text_is_the_lookup_folding_plus_casefold() -> None:
    assert n.fold_text("  Dr.  HEBA  \N{RIGHT-TO-LEFT MARK}") == "dr. heba"
    assert n.fold_text("الدكتورةُ هبة") == "الدكتوره هبه"
