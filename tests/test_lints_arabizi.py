"""Arabizi house profile. Arabizi words are quoted from docs/dataset-spec.md (`al8y`, `ll`,
`aal`, `alb`, `qanoon`, `el Qahera`, `Khaled`, `2k`...); `x6x`-style tokens are neutral
placeholders for spelling patterns the spec names without an example word."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_arabizi_profile
from afandem.lints.arabizi import arabizi_features
from afandem.scenarios import Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_arabizi_profile(Scenario.model_validate(doc))


def test_spec_example_is_clean() -> None:
    assert lint(example()) == []


@pytest.mark.parametrize(
    ("text", "feature"),
    [
        ("al8y", "digit_8"),
        ("x6x", "digit_6"),
        ("9x", "digit_9"),
        ("Khaled", "kh"),
        ("3'x", "3'"),
        ("3\N{RIGHT SINGLE QUOTATION MARK}x", "3'"),
        ("xq", "q"),
        ("al", "article"),
        ("ll", "article"),
        ("l", "article"),
        ("aal", "q_deletion"),
        ("alb", "q_deletion"),
    ],
)
def test_variant_features(text: str, feature: str) -> None:
    assert feature in arabizi_features(text)


@pytest.mark.parametrize(
    "text",
    [
        "msh 3ayza alghy ma3ad bokra",
        "a2aggelo lel 7ad el gay",
        "qanoon",
        "el Qahera",
        "2k",
        "8k",
        "8th",
        "8pm",
        "01000000017",
        "5alas",
    ],
)
def test_house_spellings_pass(text: str) -> None:
    assert arabizi_features(text) == {}


def test_names_are_exempt() -> None:
    assert arabizi_features("Khaled", exempt={"khaled"}) == {}


@pytest.mark.parametrize(("column", "field"), [("arabizi", "text"), ("cs_latin", "confirm_yes")])
def test_house_violations_are_errors(column: str, field: str) -> None:
    doc = example()
    doc["texts"][column][field] = "al8y"
    findings = [f for f in lint(doc) if f.column == column]
    assert [(f.rule, f.column, f.field, f.severity) for f in findings] == [
        ("arabizi_profile", column, field, "error"),
    ]
    assert findings[0].message == "house profile: 8 as a letter in 'al8y'"


def test_alias_names_in_state_are_exempt() -> None:
    doc = example()
    doc["texts"]["arabizi"]["text"] = "Khaled"
    assert len(lint(doc)) == 1
    doc["initial_state"]["patients"][0]["aliases"].append("Khaled")
    assert lint(doc) == []


def test_variant_identical_to_house_is_an_error() -> None:
    doc = example()
    doc["arabizi_variant"]["text"] = doc["texts"]["arabizi"]["text"]
    findings = lint(doc)
    assert [(f.column, f.severity) for f in findings] == [("arabizi_variant", "error")]
    assert findings[0].message == "the variant text is the house text"


@pytest.mark.parametrize(
    ("variant", "severity"),
    [("msh 3ayza", "error"), ("al8y", "manual"), ("ll 7ad", "manual")],
)
def test_variant_needs_two_profile_features(variant: str, severity: str) -> None:
    """The spec's own variant (`al8y` + `ll`/`l`) passes in test_spec_example_is_clean."""
    doc = example()
    doc["arabizi_variant"]["text"] = variant
    findings = lint(doc)
    assert [(f.column, f.severity) for f in findings] == [("arabizi_variant", severity)]
