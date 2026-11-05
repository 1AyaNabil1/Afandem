"""The harmful-text lint. Texts are `<...>` placeholders, lexicon terms, or the hyperbole idioms
quoted in docs/dataset-spec.md (§2 Harmful items, §3 `hyperbole_alarming`)."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_harmful_text, lexicons
from afandem.lints.harmful import enumerated_items, sentences, step_words, topic_hits
from afandem.lints.text import ALEF_LAM, is_arabic, phrase
from afandem.scenarios import COLUMNS, Scenario, load_scenarios

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "tests" / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"
LEX = lexicons.harmful()
TERMS = [
    (topic, severity, term)
    for topic, tiers in LEX.topics.items()
    for severity, terms in (("error", tiers.error), ("warning", tiers.warning))
    for term in terms
]
SPEC_IDIOMS = ["ضرسي هيموتني", "موّت الخط", "هقلب الدنيا", "والله العظيم", "my tooth is killing me"]
THREE_SENTENCES = "<the first sentence>. <the second sentence>. <the third sentence>."


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def refuse(doc: dict[str, Any]) -> dict[str, Any]:
    doc["behaviour"] = "refuse"
    doc["harm_type"] = "explicit_mismatch"
    doc["expected"].update(tool_calls=[], end_state_patch={})
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
    return doc


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_harmful_text(Scenario.model_validate(doc))


def summary(findings: list[Finding]) -> list[tuple[str, str | None, str | None, str]]:
    return [(f.rule, f.column, f.field, f.severity) for f in findings]


def test_the_spec_example_is_clean_as_act_and_as_refuse() -> None:
    assert lint(example()) == []
    assert lint(refuse(example())) == []


def test_lexicon_terms_are_distinct_after_folding() -> None:
    """So each term is reported under its own spelling, in one topic and one tier."""
    folded = [phrase(term) for _, _, term in TERMS]
    assert len(set(folded)) == len(folded)


@pytest.mark.parametrize(("topic", "severity", "term"), TERMS)
def test_every_lexicon_term_is_caught_in_a_text(topic: str, severity: str, term: str) -> None:
    assert (topic, severity, term) in topic_hits(f"<column text> {term} <column text>")


@pytest.mark.parametrize("idiom", SPEC_IDIOMS)
def test_the_spec_hyperbole_idioms_pass(idiom: str) -> None:
    assert topic_hits(f"<column text> {idiom} <column text>") == []


def test_no_list_holds_the_idioms_bare_kill_and_die_words() -> None:
    """The design of the lists: 'X is killing me' is a lexicon control, not a forbidden topic."""
    listed = {term.casefold() for _, _, term in TERMS}
    assert {"kill", "killing", "killing me", "die", "dying"}.isdisjoint(listed)
    assert topic_hits("<column text> my back is killing me <column text>") == []


def test_arabic_terms_match_with_clitics_and_the_article() -> None:
    term = next(t for _, s, t in TERMS if s == "error" and is_arabic(t) and " " not in t)
    hits = topic_hits(f"<column text> \N{ARABIC LETTER WAW}{ALEF_LAM}{term} <column text>")
    assert [(severity, shown) for _, severity, shown in hits] == [("error", term)]


def test_exempt_phrases_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    violence = LEX.topics["violence"].model_copy(update={"error": ["killing"]})
    patched = LEX.model_copy(update={"topics": {"violence": violence}})
    monkeypatch.setattr(lexicons, "harmful", lambda: patched)
    assert topic_hits("<column text> my tooth is killing me") == []
    assert topic_hits("<column text> killing <column text>") == [("violence", "error", "killing")]


def test_findings_name_the_column_field_and_tier() -> None:
    doc = example()
    error = LEX.topics["emergency"].error[0]
    warning = LEX.topics["emergency"].warning[0]
    doc["texts"]["egy"]["text"] = f"<egy text> {error} <egy text>"
    doc["texts"]["cs_latin"]["confirm_yes"] = f"<cs_latin confirm> {warning}"
    doc["arabizi_variant"]["text"] = f"<variant text> {LEX.topics['self_harm'].error[0]}"
    findings = lint(doc)
    assert summary(findings) == [
        ("harmful_text", "egy", "text", "error"),
        ("harmful_text", "cs_latin", "confirm_yes", "warning"),
        ("harmful_text", "arabizi_variant", "text", "error"),
    ]
    assert f"emergency term «{error}»" in findings[0].message
    assert "exempt" in findings[0].message
    assert f"possible emergency term «{warning}»" in findings[1].message


def test_several_terms_of_one_topic_make_one_finding() -> None:
    doc = example()
    first, second = "murder", "pistol"
    assert {first, second} <= set(LEX.topics["violence"].error)
    doc["texts"]["msa"]["text"] = f"<msa text> {first} <msa text> {second}"
    findings = lint(doc)
    assert summary(findings) == [("harmful_text", "msa", "text", "error")]
    assert f"«{first}», «{second}»" in findings[0].message


def test_lexicon_control_items_carry_no_forbidden_term() -> None:
    """Every scenario tagged as a hyperbole lexicon control passes the error tier."""
    controls = [
        item.scenario
        for root in (ROOT / "data", ROOT / "tests" / "fixtures" / "scenarios")
        for item in load_scenarios(root)
        if "hyperbole_alarming" in item.scenario.phenomena
    ]
    assert controls, "data/ holds at least one hyperbole_alarming item"
    for scenario in controls:
        errors = [f for f in check_harmful_text(scenario) if f.severity == "error"]
        assert errors == [], scenario.id


# ---------------------------------------------------------------- refuse items


def test_sentences_count_words_not_fragments() -> None:
    assert len(sentences(THREE_SENTENCES)) == 3
    assert len(sentences("<one two three>. Placeholder Name 01000000017.")) == 1
    assert len(sentences("<one two three Dr. Placeholder four five>")) == 1
    assert len(sentences("<one two three>\N{ARABIC QUESTION MARK} <four five six>")) == 2
    assert len(sentences("<one two three>\n<four five six>!")) == 2


def test_a_refuse_text_with_more_than_one_sentence_of_pretext() -> None:
    doc = refuse(example())
    doc["texts"]["en"]["text"] = THREE_SENTENCES
    findings = lint(doc)
    assert summary(findings) == [("harmful_text", "en", "text", "warning")]
    assert "3 sentences" in findings[0].message
    act = example()
    act["texts"]["en"]["text"] = THREE_SENTENCES
    assert lint(act) == []


@pytest.mark.parametrize(
    ("text", "items"),
    [
        ("<intro a b>\n1. <x y z>\n2. <x y z>", 2),
        ("<intro a b>\n\N{ARABIC-INDIC DIGIT ONE}) <x>\n\N{ARABIC-INDIC DIGIT TWO}) <y>", 2),
        ("<intro a b>\n- <x>\n- <y>\n- <z>", 3),
        ("<intro a b> 1) <x> 2) <y>", 2),
        ("<intro a b> 1,500 <x> 3.5 <y> (2026) <z>", 0),
        ("<intro a b>\n1. <x y z>", 1),
    ],
)
def test_enumerated_items(text: str, items: int) -> None:
    assert enumerated_items(text) == items


def test_a_refuse_text_with_steps() -> None:
    doc = refuse(example())
    doc["texts"]["cs"]["text"] = "<cs text>\n1. <cs item>\n2. <cs item>"
    findings = lint(doc)
    assert summary(findings) == [("harmful_text", "cs", "text", "error")]
    assert "2 enumerated items" in findings[0].message


@pytest.mark.parametrize("word", LEX.step_words)
def test_step_words_on_refuse_items(word: str) -> None:
    assert step_words(f"<column text> {word} <column text>") == [word]
    doc = refuse(example())
    doc["texts"]["arabizi"]["text"] = f"<arabizi text> {word} <arabizi text>"
    assert summary(lint(doc)) == [("harmful_text", "arabizi", "text", "warning")]
