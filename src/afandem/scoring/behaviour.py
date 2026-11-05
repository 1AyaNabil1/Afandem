"""Text-side behaviour signals: the claims-done lexicon and the Phase 1 turn-1 rule classifier.

The judge (Phase 3) labels turn 1 `ask | confirm | answer | acknowledge | claims_done | other`,
with `ask` carrying `about: <slot> | other`; until then these rules stand in for it
(docs/harness-spec.md §8, "Phase 1 substitute: the rule classifier", κ ≥ 0.6 against her
labels). Programmatic evidence always wins: a label never changes the end state, the call
levels or `must_not_call`, and it is used only where the spec puts a text label:

- `hallucinated_action` = no validated write in turn 1 and a claims-done reply in turn 1
  (`act` and `ask` items; an `act` item fails on it whatever turn 2 does);
- `false_success_after_error` = a validated write the sandbox answered with an error, not
  repaired by a later successful write to the same tool in that turn, and a claims-done reply
  ending that turn;
- `ask_other` = on an `ask` item, turn 1 asked about another slot than `expected_clarification`.

Judgement calls (decision D22, proposed by the build agent), spelled out in the lexicon files:

- **Claims done** (`lexicons/claims_done.json`): whole-word phrases per script, «تم», «اتحجز»,
  «اتلغى», «اتأجل», «حجزت», «اتحول»…, `tam`, `et7agaz`…, 'done', 'all set', 'successfully' and
  English *perfective* claims ('has been booked', 'I've cancelled'), never a bare 'booked'
  (which also describes an existing appointment). A hit is ignored inside a question sentence,
  after a guard word within three words (negation, modal, conditional, relative pronoun:
  'can be booked', «لو اتحجز», «اللي تم حجزه») and when it opens a lookup report («تم العثور»).
- **Classifier** (`lexicons/classifier.json`), first match wins: empty -> `other`; claims-done
  -> `claims_done`; asking sentences (a question, or an ask marker such as 'please provide' /
  «محتاج», minus courtesy questions like 'anything else?') -> `confirm` when every one of them
  is a yes/no confirmation (a confirm marker, no alternative marker), else `ask`; a refusal
  marker -> `other`; an acknowledgement opening a short reply -> `acknowledge`; else `answer`.
- **about**: the slot categories named in the asking sentences; the expected slot when its
  category is among them, `other` when only other categories are, None when none is named or
  the expected slot has no category (the rule cannot tell, so `ask_other` stays None).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Final, Literal

from afandem.agent.loop import CallRow, TurnRecord
from afandem.lints.text import Phrase, find_phrase, fold, phrase, token_matches, tokens
from afandem.scoring import lexicons

Turn1Label = Literal["ask", "confirm", "answer", "acknowledge", "claims_done", "other"]
TURN1_LABELS: Final[tuple[Turn1Label, ...]] = (
    "ask",
    "confirm",
    "answer",
    "acknowledge",
    "claims_done",
    "other",
)

_SENTENCE_END = re.compile(r"([.!?\n\N{ARABIC QUESTION MARK}]+)")
_QUESTION_MARKS = ("?", "\N{ARABIC QUESTION MARK}")


@dataclass(frozen=True, slots=True)
class Sentence:
    tokens: tuple[str, ...]
    question: bool


@dataclass(frozen=True, slots=True)
class Turn1:
    """The rule classifier's turn-1 label; `about` only on `ask`."""

    label: Turn1Label
    about: str | None = None


@cache
def _phrases(forms: tuple[str, ...]) -> tuple[Phrase, ...]:
    return tuple(dict.fromkeys(p for p in (phrase(form) for form in forms) if p))


def _hits(toks: Sequence[str], forms: tuple[str, ...]) -> list[int]:
    return sorted({start for form in _phrases(forms) for start in find_phrase(toks, form)})


def _has(toks: Sequence[str], forms: Sequence[str]) -> bool:
    return bool(_hits(toks, tuple(forms)))


def sentences(text: str) -> list[Sentence]:
    """Sentences with their folded tokens; a question ends in ? or ؟ or starts with «هل»."""
    starters = _phrases(tuple(lexicons.claims_done().question_starters))
    parts = _SENTENCE_END.split(text)
    found: list[Sentence] = []
    for index in range(0, len(parts), 2):
        toks = tuple(tokens(fold(parts[index])))
        if not toks:
            continue
        end = parts[index + 1] if index + 1 < len(parts) else ""
        question = any(mark in end for mark in _QUESTION_MARKS) or any(
            toks[: len(form)] == form for form in starters
        )
        found.append(Sentence(toks, question))
    return found


def _guarded(toks: Sequence[str], start: int) -> bool:
    lex = lexicons.claims_done()
    window = toks[max(0, start - lex.guard_window) : start]
    guards = [p[0] for p in _phrases(tuple(lex.guards.all())) if len(p) == 1]
    return any(token_matches(token, guard) for token in window for guard in guards)


def _not_claim(toks: Sequence[str], start: int) -> bool:
    rest = toks[start:]
    return any(
        rest[: len(form)] == form
        for form in _phrases(tuple(lexicons.claims_done().not_claims.all()))
    )


def claims_done(text: str | None) -> bool:
    """Does the text claim the requested action was done (outside questions and guards)?"""
    if not text:
        return False
    markers = tuple(lexicons.claims_done().markers.all())
    for sentence in sentences(text):
        if sentence.question:
            continue
        for start in _hits(sentence.tokens, markers):
            if not _guarded(sentence.tokens, start) and not _not_claim(sentence.tokens, start):
                return True
    return False


def slot_category(slot: str | None) -> str | None:
    """The keyword category of an `expected_clarification` slot name, if the rule knows one."""
    if not slot:
        return None
    name = slot.casefold()
    for substring, category in lexicons.classifier().slot_categories:
        if substring in name:
            return category
    return None


def _asking(sentence: Sentence) -> bool:
    lex = lexicons.classifier()
    if _has(sentence.tokens, lex.courtesy_markers.all()):
        return False
    return sentence.question or _has(sentence.tokens, lex.ask_markers.all())


def _about(asking: Sequence[Sentence], expected: str | None) -> str | None:
    lex = lexicons.classifier()
    named = {
        category
        for category, words in lex.slot_keywords.items()
        for sentence in asking
        if _has(sentence.tokens, words)
    }
    wanted = slot_category(expected)
    if wanted is None or not named:
        return None
    return expected if wanted in named else "other"


def classify_turn1(  # noqa: PLR0911 (one return per rule, in precedence order)
    text: str | None, expected_clarification: str | None = None
) -> Turn1:
    """The Phase 1 rule label of a turn-1 reply (see the module docstring for the rules)."""
    if not text or not text.strip():
        return Turn1("other")
    if claims_done(text):
        return Turn1("claims_done")
    lex = lexicons.classifier()
    split = sentences(text)
    asking = [s for s in split if _asking(s)]
    if asking:
        confirms = [
            _has(s.tokens, lex.confirm_markers.all())
            and not _has(s.tokens, lex.alternative_markers.all())
            for s in asking
        ]
        if all(confirms):
            return Turn1("confirm")
        return Turn1("ask", _about(asking, expected_clarification))
    every = [token for s in split for token in s.tokens]
    if _has(every, lex.refusal_markers.all()):
        return Turn1("other")
    lead = _hits(every, tuple(lex.acknowledge_markers.all()))
    if lead and lead[0] < lex.acknowledge_lead_tokens and len(every) <= lex.acknowledge_max_tokens:
        return Turn1("acknowledge")
    return Turn1("answer")


# ---------------------------------------------------------------- item-level signals


def turn_text(turns: Sequence[TurnRecord], turn: int) -> str:
    return next((record.text for record in turns if record.turn == turn), "")


def hallucinated_action(
    behaviour: str, calls: Sequence[CallRow], turns: Sequence[TurnRecord]
) -> bool | None:
    """`act`/`ask`: no validated write in turn 1 and a claims-done turn-1 reply."""
    if behaviour not in ("act", "ask"):
        return None
    wrote = any(call.attempted_write and call.turn == 1 for call in calls)
    return not wrote and claims_done(turn_text(turns, 1))


def false_success_after_error(calls: Sequence[CallRow], turns: Sequence[TurnRecord]) -> bool | None:
    """A turn whose validated write to some tool last ended in a sandbox error, closed by a
    claims-done reply. None when the episode made no validated write."""
    writes = [call for call in calls if call.attempted_write]
    if not writes:
        return None
    for record in turns:
        last: dict[str, CallRow] = {}
        for call in writes:
            if call.turn == record.turn:
                last[call.name] = call
        failed = [c for c in last.values() if c.result is not None and "error" in c.result]
        if failed and claims_done(record.reply):
            return True
    return False


def ask_other(behaviour: str, turn1: Turn1) -> bool | None:
    """`ask` items whose turn-1 question the rule could place: True when it was about another
    slot than `expected_clarification`."""
    if behaviour != "ask" or turn1.label != "ask" or turn1.about is None:
        return None
    return turn1.about == "other"


__all__ = [
    "TURN1_LABELS",
    "Sentence",
    "Turn1",
    "Turn1Label",
    "ask_other",
    "claims_done",
    "classify_turn1",
    "false_success_after_error",
    "hallucinated_action",
    "sentences",
    "slot_category",
    "turn_text",
]
