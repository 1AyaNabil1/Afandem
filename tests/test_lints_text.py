"""Folding, tokens and clitic-aware matching. Words are quoted from docs/dataset-spec.md."""

import pytest

from afandem.lints import lexicons
from afandem.lints.text import (
    CONJUNCTIONS,
    PREPOSITIONS,
    arabic_matches,
    contains_phrase,
    fold,
    fold_name,
    light_fold,
    normalise_cs_articles,
    phrase,
    tokens,
    words_with_diacritics,
)


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("أجله", "اجله"),
        ("غداً", "غدا"),
        ("إلى", "الي"),
        ("يُرجى", "يرجي"),
        ("عايزة", "عايزه"),
        ("٠١٠٠٠٠٠٠٠١٧", "01000000017"),
        ("۰۱۰", "010"),
        ("الـ order", "ال order"),
        ("ی ک", "ي ك"),
        ("Mona Mahmoud", "mona mahmoud"),
        ("منى\N{ZERO WIDTH NON-JOINER}", "مني"),
        ("\N{RIGHT-TO-LEFT MARK}منى\N{LEFT-TO-RIGHT MARK}", "مني"),
    ],
)
def test_fold(raw: str, folded: str) -> None:
    assert fold(raw) == folded


def test_light_fold_keeps_letter_shapes() -> None:
    assert light_fold("عايزة") == "عايزة"
    assert light_fold("أجله") == "أجله"
    assert light_fold("يُرجى") == "يرجى"


def test_fold_name_joins_abd() -> None:
    assert fold_name("منى محمود عبد الحليم") == fold_name("مني محمود عبدالحليم")


def test_tokens_split_scripts() -> None:
    assert tokens(fold("الorder")) == ["ال", "order"]
    assert tokens(fold("msh 3ayza a3mel cancel")) == ["msh", "3ayza", "a3mel", "cancel"]
    assert tokens(fold("٨/١١")) == ["8", "11"]


@pytest.mark.parametrize("form", ["ال order", "الorder", "الـ order", "الـorder"])
def test_cs_article_forms_normalise(form: str) -> None:
    assert normalise_cs_articles(form) == "ال order"


@pytest.mark.parametrize(
    ("token", "form", "expected"),
    [
        ("الحد", "الحد", True),
        ("للحد", "الحد", True),
        ("إلينا", "إلى", False),
        ("أهلا", "هل", False),
        ("الحد", "حد", False),
    ],
)
def test_arabic_matches_spec_cases(token: str, form: str, expected: bool) -> None:
    assert arabic_matches(fold(token), fold(form)) is expected


def test_proclitics_on_long_and_short_forms() -> None:
    long_form, short_form = fold("الذي"), fold("هل")
    for proclitic in (*CONJUNCTIONS, *PREPOSITIONS, CONJUNCTIONS[0] + PREPOSITIONS[0]):
        assert arabic_matches(proclitic + long_form, long_form)
        assert not arabic_matches(proclitic + long_form, long_form, proclitics=False)
    assert arabic_matches(CONJUNCTIONS[0] + short_form, short_form)
    for proclitic in (CONJUNCTIONS[1], *PREPOSITIONS):
        assert not arabic_matches(proclitic + short_form, short_form)


def test_enclitics_are_never_stripped() -> None:
    assert not arabic_matches(fold("الحد") + fold("ه"), fold("الحد"))


def test_phrases_match_on_token_sequences() -> None:
    text = tokens(fold("مش عايزة ألغي معاد بكرة"))
    assert contains_phrase(text, phrase("بكرة"))
    assert contains_phrase(text, phrase("مش عايزة"))
    assert not contains_phrase(text, phrase("بعد بكرة"))


def test_words_with_diacritics() -> None:
    assert words_with_diacritics("يُرجى أجله") == ["يُرجى"]
    assert words_with_diacritics("غداً") == ["غداً"]
    assert words_with_diacritics("أجله الحد") == []


def test_every_lexicon_loads() -> None:
    assert len(lexicons.egyptian().markers) >= 18
    assert len(lexicons.msa().msa_isms) == 31
    assert set(lexicons.dates().weekdays) == {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
    assert sorted(lexicons.dates().months) == list(range(1, 13))
    assert lexicons.follow_up().ambiguous_alone == ["خلاص", "5alas"]
    assert lexicons.code_switch().tool_cue_words[0] == "cancel"
    assert lexicons.arabizi().q_words == ["qanoon", "qahera"]
    assert lexicons.numbers().forms["ألف وربع"] == 1250
    assert lexicons.gender().masculine[0] == "عايز"


def test_lexicon_phrases_deduplicate_on_folding() -> None:
    shown = [form for form, _ in lexicons.phrases(["عايزة", "عايزه", "عايز"])]
    assert shown == ["عايزة", "عايز"]
