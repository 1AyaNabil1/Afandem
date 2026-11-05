"""CS insertions. Texts are quoted from docs/dataset-spec.md (the §1 example, the article
forms, the CS-Latin example) or are neutral placeholder tokens."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_cs_insertions
from afandem.lints.codeswitch import _cover, latin_runs
from afandem.scenarios import Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def insertions(*items: tuple[str, bool]) -> list[dict[str, Any]]:
    return [{"text": text, "tool_cue": cue} for text, cue in items]


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_cs_insertions(Scenario.model_validate(doc))


def messages(findings: list[Finding], column: str | None) -> list[str]:
    return [f.message for f in findings if f.column == column]


def test_spec_example_is_clean() -> None:
    assert lint(example()) == []


@pytest.mark.parametrize("count", [0, 4])
def test_declared_count_is_one_to_three(count: int) -> None:
    doc = example()
    items = insertions(("cancel", True), ("reschedule", True), ("order", False), ("book", True))
    for column in ("cs", "cs_latin"):
        doc["texts"][column]["insertions"] = items[:count]
    findings = lint(doc)
    for column in ("cs", "cs_latin"):
        assert f"{count} declared insertions; CS needs 1-3 content insertions" in messages(
            findings, column
        )


def test_declared_insertion_must_be_in_the_text() -> None:
    doc = example()
    doc["texts"]["cs_latin"]["text"] = "msh 3ayza a3mel cancel lel ma3ad"
    assert messages(lint(doc), "cs_latin") == ["declared insertion 'reschedule' is not in the text"]


def test_discourse_marker_is_not_an_insertion() -> None:
    doc = example()
    for column in ("cs", "cs_latin"):
        doc["texts"][column]["insertions"] = insertions(("cancel", True), ("ok", False))
    assert "'ok' is a discourse marker, not a content insertion" in messages(lint(doc), "cs")


def test_tool_cue_words_need_tool_cue_true() -> None:
    doc = example()
    for column in ("cs", "cs_latin"):
        doc["texts"][column]["insertions"] = insertions(("cancel", False), ("reschedule", False))
    assert messages(lint(doc), "cs") == ["'cancel' names a tool (cancel): tool_cue must be true"]


@pytest.mark.parametrize("text", ["ال order", "الorder", "الـ order"])
def test_article_forms_are_normalised(text: str) -> None:
    doc = example()
    doc["texts"]["cs"]["text"] = text
    doc["texts"]["cs"]["insertions"] = insertions(("order", False))
    assert messages(lint(doc), "cs") == []


def test_undeclared_english_is_an_error() -> None:
    doc = example()
    doc["texts"]["cs"]["text"] = "ال order"
    doc["texts"]["cs"]["insertions"] = insertions(("cancel", True))
    assert messages(lint(doc), "cs") == [
        "declared insertion 'cancel' is not in the text",
        "undeclared English insertion 'order' (declare it in insertions; it counts toward the 1-3)",
    ]


def test_discourse_markers_and_names_are_not_insertions() -> None:
    doc = example()
    for text in ("أيوه، ok.", "Mona Mahmoud"):
        doc["texts"]["cs"]["text"] = text
        doc["texts"]["cs"]["insertions"] = []
        assert messages(lint(doc), "cs") == [
            "0 declared insertions; CS needs 1-3 content insertions"
        ]


def test_cs_and_cs_latin_carry_the_same_insertions() -> None:
    doc = example()
    doc["texts"]["cs_latin"]["insertions"][1]["tool_cue"] = False
    assert messages(lint(doc), None) == [
        "cs and cs_latin must carry the same insertions (text and tool_cue, in order)"
    ]


def test_runs_and_cover() -> None:
    assert latin_runs("aaa bbb") == [("aaa", "bbb")]
    assert latin_runs("aaa, bbb") == [("aaa",), ("bbb",)]
    assert _cover(("aaa", "bbb"), [("aaa", "bbb")]) == []
    assert _cover(("aaa", "bbb", "ccc"), [("bbb",)]) == [("aaa",), ("ccc",)]
    assert _cover(("aaa", "bbb"), []) == [("aaa", "bbb")]
