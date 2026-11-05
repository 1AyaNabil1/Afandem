"""Egyptian markers, MSA-isms, the MSA Egyptian-syntax lint, diacritics and gender.

Every Arabic word here is quoted from docs/dataset-spec.md (lexicons and examples); texts
are single words or `<column text>` placeholders.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import (
    Finding,
    check_diacritics,
    check_egyptian_markers,
    check_gender,
    check_msa_isms,
    check_msa_syntax,
    lexicons,
)
from afandem.lints.egyptian import egyptian_markers, msa_isms, msa_syntax_problems
from afandem.lints.text import CONJUNCTIONS
from afandem.scenarios import Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def scenario_with(column: str, field: str, text: str, **top: Any) -> Scenario:
    doc = example()
    doc["texts"][column][field] = text
    doc.update(top)
    return Scenario.model_validate(doc)


def where(findings: list[Finding]) -> list[tuple[str, str | None, str | None, str]]:
    return [(f.rule, f.column, f.field, f.severity) for f in findings]


# --- Egyptian markers -----------------------------------------------------------------


def test_spec_example_is_clean() -> None:
    scenario = Scenario.model_validate(example())
    for check in (check_egyptian_markers, check_msa_isms, check_msa_syntax, check_diacritics):
        assert check(scenario) == []
    assert check_gender(scenario) == []


@pytest.mark.parametrize("word", ["مش", "اللي", "عايزة", "عايزه", "بتاعي", "دلوقتي", "كده"])
def test_markers_found(word: str) -> None:
    strong, _ = egyptian_markers(word)
    assert strong


@pytest.mark.parametrize("column", ["egy", "cs"])
def test_no_marker_is_an_error(column: str) -> None:
    findings = check_egyptian_markers(scenario_with(column, "text", "<text>"))
    assert where(findings) == [("egyptian_marker", column, "text", "error")]


@pytest.mark.parametrize("word", ["هأحجز", "هيموتني"])
def test_verb_prefix_alone_is_a_warning(word: str) -> None:
    findings = check_egyptian_markers(scenario_with("egy", "text", word))
    assert where(findings) == [("egyptian_marker", "egy", "text", "warning")]


# --- MSA-isms in EGY / CS -------------------------------------------------------------


@pytest.mark.parametrize("word", ["هل", "لماذا", "غداً", "إلى", "أريد", "يُرجى"])
def test_msa_isms_found(word: str) -> None:
    assert msa_isms(word)


@pytest.mark.parametrize("word", ["أهلا", "إلينا", "<egy text>"])
def test_whole_word_passes(word: str) -> None:
    assert msa_isms(word) == []


def test_msa_ism_behind_a_proclitic() -> None:
    assert msa_isms(CONJUNCTIONS[0] + "الذي") == ["الذي"]


def test_exact_only_disables_proclitics(monkeypatch: pytest.MonkeyPatch) -> None:
    patched = lexicons.msa().model_copy(update={"exact_only": ["الذي"]})
    monkeypatch.setattr(lexicons, "msa", lambda: patched)
    assert msa_isms(CONJUNCTIONS[0] + "الذي") == []
    assert msa_isms("الذي") == ["الذي"]


@pytest.mark.parametrize(
    ("column", "field"), [("egy", "text"), ("cs", "text"), ("egy", "confirm_yes")]
)
def test_msa_ism_findings(column: str, field: str) -> None:
    findings = check_msa_isms(scenario_with(column, field, "هل"))
    assert where(findings) == [("msa_ism", column, field, "error")]


def test_msa_isms_are_not_checked_in_msa() -> None:
    assert check_msa_isms(scenario_with("msa", "text", "هل")) == []


# --- MSA Egyptian-syntax --------------------------------------------------------------


@pytest.mark.parametrize("word", ["مش", "بتاع", "بتاعي", "عايز", "هأحجز", "سوف", "بل", "لذا", "إنّ"])
def test_msa_errors(word: str) -> None:
    errors, _ = msa_syntax_problems(word)
    assert errors


@pytest.mark.parametrize("word", ["فيه", "هيموتني", "إن"])
def test_msa_warnings(word: str) -> None:
    errors, warnings = msa_syntax_problems(word)
    assert errors == []
    assert warnings


@pytest.mark.parametrize("word", ["أريد", "الأحد", "<msa text>"])
def test_msa_passes(word: str) -> None:
    assert msa_syntax_problems(word) == ([], [])


def test_msa_syntax_findings() -> None:
    findings = check_msa_syntax(scenario_with("msa", "confirm_yes", "مش"))
    assert where(findings) == [("msa_egyptian_syntax", "msa", "confirm_yes", "error")]
    findings = check_msa_syntax(scenario_with("msa", "text", "فيه"))
    assert where(findings) == [("msa_egyptian_syntax", "msa", "text", "warning")]


# --- diacritics -----------------------------------------------------------------------


@pytest.mark.parametrize("column", ["egy", "cs", "msa"])
@pytest.mark.parametrize("word", ["يُرجى", "غداً", "أأجّله"])
def test_diacritics_are_errors(column: str, word: str) -> None:
    findings = check_diacritics(scenario_with(column, "text", word))
    assert where(findings) == [("diacritics", column, "text", "error")]


def test_diacritics_not_checked_in_arabizi_or_en() -> None:
    assert check_diacritics(scenario_with("en", "text", "يُرجى")) == []


# --- gender ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gender", "column", "text", "flagged"),
    [
        ("f", "egy", "عايز", True),
        ("f", "egy", "عايزة", False),
        ("f", "egy", "عايزه", False),
        ("m", "egy", "عايزة", True),
        ("m", "egy", "عايز", False),
        ("m", "egy", "عايزه", False),
        ("f", "arabizi", "3ayez", True),
        ("m", "cs_latin", "3ayza", True),
        ("m", "arabizi", "3ayez", False),
    ],
)
def test_gender_heuristic(gender: str, column: str, text: str, flagged: bool) -> None:
    doc = neutral()
    doc["gender"] = gender
    doc["texts"][column]["text"] = text
    findings = check_gender(Scenario.model_validate(doc))
    expected = [("gender", column, "text", "warning")] if flagged else []
    assert where(findings) == expected


def neutral() -> dict[str, Any]:
    """The example with every Arabic and Arabizi text replaced by a placeholder."""
    doc = example()
    for column in ("msa", "egy", "arabizi", "cs", "cs_latin"):
        doc["texts"][column]["text"] = f"<{column} text>"
    doc["arabizi_variant"]["text"] = "<variant text>"
    return doc


def test_gender_checks_the_variant() -> None:
    doc = neutral()
    doc["arabizi_variant"]["text"] = "3ayez"
    findings = check_gender(Scenario.model_validate(doc))
    assert where(findings) == [("gender", "arabizi_variant", "text", "warning")]
