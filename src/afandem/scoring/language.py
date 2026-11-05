"""Reply language, level 1 (docs/harness-spec.md §8; methodology §3.1).

The scored text is the last assistant turn with any text (the reply a user would read last).

1. Tokens with no letter (digits, times, phones) and ID-shaped tokens (with `_`, `@` or `/`,
   three or more digits mixed with letters such as `acc9001` or `2026-11-08T10`, or a number
   with a unit or ordinal suffix such as `5pm`, `2nd`, `3k`) are dropped.
2. Majority script over the remaining **alphabetic characters**: Arabic letters against Latin
   letters; Arabic when its share is above 0.5.
3. A Latin-majority reply is **Arabizi** when it holds at least two distinct Arabizi lexicon
   words (`lexicons/reply_language.json`; distinct, so a romanised «El Banna, El Sayed» counts
   once) or any token matching `(^|[a-z])[23578]([a-z]|$)` (a digit used as a letter); else
   **English**.

Acceptable per input column: `en` English; `msa`, `egy`, `cs` Arabic script; `arabizi` and
`cs_latin` {Arabizi, Arabic script} (Arabizi typists read Arabic script natively). An empty reply
is `none` and has no match value (it is a validity flag, not a language mismatch). Level 2
(variety, judge, 20% sample) is Phase 3.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Literal

from afandem.agent.loop import TurnRecord
from afandem.scenarios.schema import Column
from afandem.scoring import lexicons

type ReplyLanguage = Literal["arabic", "arabizi", "english", "none"]

ACCEPTABLE: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({"english"}),
    "msa": frozenset({"arabic"}),
    "egy": frozenset({"arabic"}),
    "cs": frozenset({"arabic"}),
    "arabizi": frozenset({"arabizi", "arabic"}),
    "cs_latin": frozenset({"arabizi", "arabic"}),
}
ARABIC_SHARE: Final = 0.5

_EDGE_PUNCTUATION = re.compile(r"^[\W_]+|[\W_]+$")
_DIGIT_LETTER = re.compile(r"(^|[a-z])[23578]([a-z]|$)")
_ID_MARKS = ("_", "@", "/")


def _is_arabic(char: str) -> bool:
    return "ARABIC" in unicodedata.name(char, "")


def _is_latin(char: str) -> bool:
    return "LATIN" in unicodedata.name(char, "")


def _unit_token(token: str) -> bool:
    suffixes = "|".join(re.escape(s) for s in lexicons.reply_language().unit_suffixes)
    return re.fullmatch(rf"[0-9]+(?:[.,][0-9]+)?(?:{suffixes})", token) is not None


def kept_tokens(text: str) -> list[str]:
    """Lowercased word tokens with at least one letter, IDs and unit numbers dropped."""
    kept: list[str] = []
    for raw in unicodedata.normalize("NFKC", text).split():
        token = _EDGE_PUNCTUATION.sub("", raw).casefold()
        if not token or not any(c.isalpha() for c in token):
            continue
        if any(mark in token for mark in _ID_MARKS):
            continue
        if sum(c.isdigit() for c in token) >= 3 or _unit_token(token):
            continue
        kept.append(token)
    return kept


def detect(text: str | None) -> ReplyLanguage:
    """`arabic`, `arabizi`, `english` or `none` (no alphabetic text)."""
    toks = kept_tokens(text or "")
    arabic = sum(_is_arabic(c) for token in toks for c in token if c.isalpha())
    latin = sum(_is_latin(c) for token in toks for c in token if c.isalpha())
    if arabic + latin == 0:
        return "none"
    if arabic / (arabic + latin) > ARABIC_SHARE:
        return "arabic"
    lex = lexicons.reply_language()
    words = set(lex.arabizi_words)
    latin_tokens = [t for t in toks if any(_is_latin(c) for c in t)]
    if len({t for t in latin_tokens if t in words}) >= lex.min_word_hits:
        return "arabizi"
    if any(_DIGIT_LETTER.search(t) for t in latin_tokens):
        return "arabizi"
    return "english"


def reply_text(turns: Sequence[TurnRecord]) -> str:
    """The last turn's text that is not empty."""
    for record in reversed(turns):
        if record.text.strip():
            return record.text
    return ""


def language_match(column: Column | str, detected: ReplyLanguage) -> bool | None:
    if detected == "none":
        return None
    return detected in ACCEPTABLE[column]


__all__ = ["ACCEPTABLE", "ReplyLanguage", "detect", "kept_tokens", "language_match", "reply_text"]
