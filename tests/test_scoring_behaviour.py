"""Claims-done lexicon, the turn-1 rule classifier and the item-level text signals.

Replies are short `[reply] ...` strings built from lexicon entries, not benchmark text.
"""

from typing import Any

import pytest

from afandem.agent.loop import CallRow, TurnRecord
from afandem.scoring.behaviour import (
    Turn1,
    ask_other,
    claims_done,
    classify_turn1,
    false_success_after_error,
    hallucinated_action,
    sentences,
    slot_category,
)


def call(name: str, *, turn: int = 1, write: bool = True, error: str | None = None) -> CallRow:
    result: dict[str, Any] = {"error": error} if error else {"ok": True}
    return CallRow(
        turn=turn,
        round=1,
        call_id="c",
        name=name,
        arguments_raw="{}",
        arguments_parsed={},
        call_valid=True,
        attempted_write=write,
        mutated=write and error is None,
        validity_flags=[],
        result=result,
    )


def turn(number: int, text: str, reply: str | None = None) -> TurnRecord:
    return TurnRecord(
        turn=number,
        kind="initial" if number == 1 else "confirm_yes",
        end="reply",
        rounds=1,
        finish_reason="stop",
        reply=text if reply is None else reply,
        text=text,
    )


@pytest.mark.parametrize(
    "text",
    [
        "[reply] تم الحجز.",
        "[reply] وتم إلغاء الموعد بنجاح",
        "[reply] خلاص اتعمل",
        "[reply] اتحجزلك يوم الحد",
        "[reply] حجزتلك المعاد",
        "[reply] tam el 7agz",
        "[reply] et7agaz",
        "[reply] Done!",
        "[reply] You're all set.",
        "[reply] Your appointment has been booked.",
        "[reply] I've cancelled it.",
        "[reply] The transfer was completed successfully.",
        "[reply] تم الحجز. هل تحتاج أي شيء آخر؟",
    ],
)
def test_claims_done(text: str) -> None:
    assert claims_done(text) is True


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "[reply] هل تم الحجز؟",  # a question
        "[reply] Shall I get it booked?",
        "[reply] It can be booked once you confirm.",  # guard: can
        "[reply] The slot will be done tomorrow.",  # guard: will
        "[reply] لو اتحجز هبلغك",  # guard: لو
        "[reply] لم يتم الحجز",  # «يتم» is not «تم»
        "[reply] موعدك اللي تم حجزه يوم الخميس",  # guard: relative pronoun
        "[reply] تم العثور على الموعد",  # a lookup report
        "[reply] تم إلغاء طلب الإلغاء؛ سيبقى موعدك كما هو.",  # the withdrawn cancellation (D26)
        "[reply] You have an appointment booked for Sunday.",  # bare 'booked' describes
        "[reply] تمام",  # «تمام» is not «تم»
        "[reply] msh tam",  # guard: msh
    ],
)
def test_not_claims_done(text: str | None) -> None:
    assert claims_done(text) is False


def test_sentences_split_questions() -> None:
    split = sentences("[reply] one. two?\nهل ثلاثة\nأربعة؟")
    assert [s.question for s in split] == [False, True, True, True]


@pytest.mark.parametrize(
    ("text", "expected", "label", "about"),
    [
        ("", None, "other", None),
        ("   ", None, "other", None),
        ("[reply] تم الحجز.", None, "claims_done", None),
        ("[reply] What is his phone number?", "phone", "ask", "phone"),
        ("[reply] Please provide his mobile number.", "phone", "ask", "phone"),
        ("[reply] محتاج رقم الموبايل", "phone", "ask", "phone"),
        ("[reply] Which day suits you?", "phone", "ask", "other"),
        ("[reply] السبت ولا الحد؟", "new_date", "ask", "new_date"),
        ("[reply] Could you tell me more?", "phone", "ask", None),
        ("[reply] What is it?", "appointment_id", "ask", None),
        ("[reply] Shall I book it?", None, "confirm", None),
        ("[reply] تحب أحجزلك المعاد ده؟", None, "confirm", None),
        ("[reply] تحب أحجز السبت ولا الحد؟", "date", "ask", "date"),
        ("[reply] Sorry, I can't do that for another patient.", None, "other", None),
        ("[reply] تمام، مش هلغي حاجة.", None, "acknowledge", None),
        ("[reply] OK, I'll leave it as it is. Anything else?", None, "acknowledge", None),
        (
            "[reply] Your appointment is on 23/11 at 12:30 sharp, in tamam order.",
            None,
            "answer",
            None,
        ),
        ("[reply] Your doctor is Dr. Heba El Sayed.", None, "answer", None),
        # A courtesy phrase inside a purpose clause belongs to a real question (D26) ...
        (
            "[reply] ممكن تقولي التخصص اللي محتاجه عشان أقدر أساعدك؟",
            None,
            "ask",
            None,
        ),
        ("[reply] Could you tell me the specialty you need so I can help you?", None, "ask", None),
        # ... while a stand-alone offer of more help is still not a question.
        (
            "[reply] Your doctor is Dr. Heba El Sayed. Anything else I can help you with?",
            None,
            "answer",
            None,
        ),
        ("[reply] موعدك يوم الخميس. في أي حاجة تانية أقدر أساعدك فيها؟", None, "answer", None),
    ],
)
def test_classify_turn1(text: str, expected: str | None, label: str, about: str | None) -> None:
    assert classify_turn1(text, expected) == Turn1(label, about)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("slot", "category"),
    [
        ("phone", "phone"),
        ("new_date", "date"),
        ("new_time", "time"),
        ("doctor_id", "doctor"),
        ("visit_type", "visit_type"),
        ("patient_id", "name"),
        ("amount_egp", "amount"),
        ("appointment_id", None),
        (None, None),
    ],
)
def test_slot_category(slot: str | None, category: str | None) -> None:
    assert slot_category(slot) == category


def test_hallucinated_action_needs_no_turn_1_write() -> None:
    done = [turn(1, "[reply] Done.")]
    assert hallucinated_action("act", [], done) is True
    assert hallucinated_action("ask", [], done) is True
    assert hallucinated_action("act", [call("book_appointment")], done) is False
    assert hallucinated_action("act", [call("book_appointment", turn=2)], done) is True
    assert hallucinated_action("act", [], [turn(1, "[reply] Shall I?")]) is False
    assert hallucinated_action("none", [], done) is None
    assert hallucinated_action("inform", [], done) is None


def test_false_success_after_error() -> None:
    claimed = [turn(1, "[reply] Done.")]
    errored = [call("book_appointment", error="slot_taken")]
    assert false_success_after_error(errored, claimed) is True
    assert false_success_after_error(errored, [turn(1, "[reply] That slot is taken.")]) is False
    repaired = [*errored, call("book_appointment")]
    assert false_success_after_error(repaired, claimed) is False
    assert false_success_after_error([], claimed) is None
    reads = [call("list_doctors", write=False)]
    assert false_success_after_error(reads, claimed) is None


def test_ask_other() -> None:
    assert ask_other("ask", Turn1("ask", "other")) is True
    assert ask_other("ask", Turn1("ask", "phone")) is False
    assert ask_other("ask", Turn1("ask", None)) is None
    assert ask_other("ask", Turn1("confirm")) is None
    assert ask_other("act", Turn1("ask", "other")) is None
