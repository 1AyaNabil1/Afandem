"""Follow-up and confirm lexicon. Words are quoted from docs/dataset-spec.md (the yes/no
lexicons, «خلاص», the follow-up example «أيوه، بعد الضهر» and the §1 confirms)."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_follow_up_lexicon
from afandem.scenarios import COLUMNS, Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def as_ask(doc: dict[str, Any]) -> dict[str, Any]:
    doc["behaviour"] = "ask"
    doc["expected"]["expected_clarification"] = "new_time"
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
        doc["texts"][name]["follow_up"] = doc["texts"][name]["text"]
    return doc


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_follow_up_lexicon(Scenario.model_validate(doc))


def where(findings: list[Finding]) -> list[tuple[str | None, str | None, str]]:
    return [(f.column, f.field, f.severity) for f in findings]


def test_spec_example_is_clean() -> None:
    assert lint(example()) == []


@pytest.mark.parametrize("column", ["egy", "cs", "arabizi", "cs_latin"])
def test_confirm_without_a_yes_word_is_an_error(column: str) -> None:
    doc = example()
    doc["texts"][column]["confirm_yes"] = f"<{column} confirm>"
    assert where(lint(doc)) == [(column, "confirm_yes", "error")]


@pytest.mark.parametrize("column", ["en", "msa"])
def test_no_lexicon_for_en_and_msa(column: str) -> None:
    doc = example()
    doc["texts"][column]["confirm_yes"] = f"<{column} confirm>"
    assert lint(doc) == []


@pytest.mark.parametrize("word", ["أيوه", "أيوة", "اه", "آه", "أكيد", "تمام", "ماشي", "يلا", "اوك"])
def test_yes_words(word: str) -> None:
    doc = example()
    doc["texts"]["egy"]["confirm_yes"] = word
    assert lint(doc) == []


def test_follow_up_without_a_yes_word_is_a_warning() -> None:
    findings = lint(as_ask(example()))
    assert where(findings) == [
        ("egy", "follow_up", "warning"),
        ("arabizi", "follow_up", "warning"),
        ("cs", "follow_up", "warning"),
        ("cs_latin", "follow_up", "warning"),
    ]


@pytest.mark.parametrize(("column", "word"), [("egy", "خلاص"), ("arabizi", "5alas")])
def test_khalas_never_alone(column: str, word: str) -> None:
    doc = example()
    doc["texts"][column]["confirm_yes"] = word
    findings = lint(doc)
    assert where(findings) == [(column, "confirm_yes", "error"), (column, "confirm_yes", "error")]
    assert "is ambiguous and never stands without a yes word" in findings[1].message


def test_khalas_with_a_yes_word_passes() -> None:
    doc = example()
    doc["texts"]["egy"]["confirm_yes"] = "خلاص تمام"
    assert lint(doc) == []


@pytest.mark.parametrize("word", ["بلاش", "لأ"])
def test_no_word_in_a_confirm(word: str) -> None:
    doc = example()
    doc["texts"]["egy"]["confirm_yes"] = word
    assert where(lint(doc)) == [("egy", "confirm_yes", "error"), ("egy", "confirm_yes", "warning")]


@pytest.mark.parametrize(
    ("time", "flagged"),
    [("15:30", True), (["15:00", "15:30", "16:00"], False), (["15:30"], True)],
)
def test_period_word_in_follow_up_needs_a_window(time: object, flagged: bool) -> None:
    doc = as_ask(example())
    doc["texts"]["egy"]["follow_up"] = "أيوه، بعد الضهر"
    doc["expected"]["tool_calls"][0]["args"]["time"] = time
    egy = [f for f in lint(doc) if f.column == "egy"]
    if flagged:
        assert where(egy) == [("egy", "follow_up", "error")]
        assert "makes the gold a window" in egy[0].message
    else:
        assert egy == []


def test_period_word_without_a_time_argument_is_ignored() -> None:
    doc = as_ask(example())
    doc["texts"]["egy"]["follow_up"] = "أيوه، بعد الضهر"
    del doc["expected"]["tool_calls"][0]["args"]["time"]
    assert [f for f in lint(doc) if f.column == "egy"] == []
