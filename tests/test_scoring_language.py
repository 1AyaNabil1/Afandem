"""Reply language level 1: majority script, Arabizi detection and the per-column sets.

Replies are short constructed strings (lexicon words and placeholders), not benchmark text.
"""

import pytest

from afandem.agent.loop import TurnRecord
from afandem.scoring.language import ACCEPTABLE, detect, kept_tokens, language_match, reply_text

ARABIC = [
    "[reply] تم الحجز يوم الأحد",
    "[reply] موعدك مع د. هبة السيد (Dr. Heba) الساعة 17:00",
    "**تم**",
    "[r] تم",
]
ARABIZI = [
    "[reply] tamam, msh hal8y",
    "[reply] 3ashan kda",
    "[reply] el ma3ad bokra",
    "[reply] et7agaz",
    "[reply] ok, 5alas",
]
ENGLISH = [
    "[reply] Your appointment is booked for 5pm on the 2nd.",
    "[reply] Dr. Heba El Sayed and Dr. Hala El Banna",  # one Arabizi word ('el'), counted once
    "[reply] Your id is appt_0001 and the phone +201000000017, ref acc9001.",
    "[reply] Done.",
    "[reply] The amount is 3k EGP.",
]


@pytest.mark.parametrize("text", ARABIC)
def test_arabic_script_replies(text: str) -> None:
    assert detect(text) == "arabic"


@pytest.mark.parametrize("text", ARABIZI)
def test_arabizi_replies(text: str) -> None:
    assert detect(text) == "arabizi"


@pytest.mark.parametrize("text", ENGLISH)
def test_english_replies(text: str) -> None:
    assert detect(text) == "english"


@pytest.mark.parametrize("text", [None, "", "12:30 2026-11-08 +201000000017", "appt_0001 :)"])
def test_no_alphabetic_text(text: str | None) -> None:
    assert detect(text) == "none"


def test_ids_and_numbers_are_never_arabizi_hits() -> None:
    assert kept_tokens("0100 appt_0001 a7a 5pm 2nd 3rd 2026-11-08T10 x@y.z") == ["a7a"]


@pytest.mark.parametrize(
    ("column", "detected", "match"),
    [
        ("en", "english", True),
        ("en", "arabic", False),
        ("egy", "arabic", True),
        ("egy", "english", False),
        ("msa", "arabizi", False),
        ("cs", "arabic", True),
        ("arabizi", "arabizi", True),
        ("arabizi", "arabic", True),
        ("arabizi", "english", False),
        ("cs_latin", "arabic", True),
        ("egy", "none", None),
    ],
)
def test_language_match(column: str, detected: str, match: bool | None) -> None:
    assert language_match(column, detected) is match  # type: ignore[arg-type]


def test_every_column_has_an_acceptable_set() -> None:
    assert set(ACCEPTABLE) == {"en", "msa", "egy", "arabizi", "cs", "cs_latin"}


def test_reply_text_is_the_last_turn_with_text() -> None:
    def record(number: int, text: str) -> TurnRecord:
        return TurnRecord(
            turn=number,
            kind="initial",
            end="reply",
            rounds=1,
            finish_reason="stop",
            reply=text,
            text=text,
        )

    assert reply_text([record(1, "first"), record(2, "second")]) == "second"
    assert reply_text([record(1, "first"), record(2, "  ")]) == "first"
    assert reply_text([]) == ""
