"""Name and phone folding, the identity lookup and the state-collision lint.

Lookup order: the phone, normalised to E.164, first; otherwise the folded name, which must have
at least two tokens, matched against each record's `name` and tri-script `aliases`. A query
matches a form when the two are equal ignoring spaces, or when the query's tokens are the first
tokens of the form ("Mona Mahmoud" matches "Mona Mahmoud Abdel Halim"). One hit returns the id,
none `{"error": "not_found"}`, several `{"ambiguous": [ids]}` (the correct behaviour is to ask).

Arabic folding: NFKC; strip tashkeel, tatweel, ZWNJ/ZWJ and bidi marks; أ إ آ ٱ → ا, ى → ي,
ة → ه, Persian ی → ي and ک → ك; «عبد الرحمن» and «عبدالرحمن» fold alike.

Latin folding: NFKC, lowercase, accents dropped, hyphens and spaces stripped, doubled letters
collapsed, and the clusters Mohamed/Mohammed/Muhammad, Ahmed/Ahmad, Abdelrahman/Abd El Rahman/
Abdul Rahman, Youssef/Yousef, Khaled/Khalid, Fatma/Fatima, Nour/Noor and Mahmoud/Mahmood mapped
to one spelling. The particles `abd`/`abdel`/`abdul` and `el`/`al` join the next token, so
"Heba El Sayed" has two tokens like «هبة السيد». Arabizi spellings are not transliterated:
records list them as aliases.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

MIN_NAME_TOKENS = 2

# Bidi marks, embeddings and isolates, ZWNJ/ZWJ, the Arabic letter mark and BOM.
_INVISIBLE: dict[int, None] = dict.fromkeys(
    [0x200C, 0x200D, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x061C, 0xFEFF]
)
# Arabic-Indic (U+0660..) and Extended Arabic-Indic / Persian (U+06F0..) digits.
_DIGITS: dict[int, int] = {base + i: ord("0") + i for base in (0x0660, 0x06F0) for i in range(10)}
_ALEF, _YEH, _HEH, _KAF = 0x0627, 0x064A, 0x0647, 0x0643
_ARABIC_LETTERS: dict[int, int] = {
    0x0623: _ALEF,  # alef with hamza above
    0x0625: _ALEF,  # alef with hamza below
    0x0622: _ALEF,  # alef with madda
    0x0671: _ALEF,  # alef wasla
    0x0649: _YEH,  # alef maksura
    0x0629: _HEH,  # teh marbuta
    0x06CC: _YEH,  # Persian yeh
    0x06A9: _KAF,  # Persian keheh
}


def _char_class(*ranges: tuple[int, int]) -> re.Pattern[str]:
    return re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in ranges) + "]")


# Tashkeel, Quranic marks, superscript alef and tatweel (U+0640).
_TASHKEEL = _char_class(
    (0x0610, 0x061A),
    (0x064B, 0x065F),
    (0x0670, 0x0670),
    (0x06D6, 0x06DC),
    (0x06DF, 0x06E8),
    (0x06EA, 0x06ED),
    (0x0640, 0x0640),
)
_ARABIC_CHAR = _char_class(
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)
)
_ABD = "".join(map(chr, (0x0639, 0x0628, 0x062F)))  # the particle "abd"
_ABD_JOIN = re.compile(rf"(?<!\S){_ABD}\s+(?=\S)")
_DOUBLED = re.compile(r"([a-z])\1+")
_ABD_LATIN = re.compile(r"abd(?:el|ul|al|u|e|a)?([a-z]{3,})")
_LATIN_ABD_PARTICLES = frozenset({"abd", "abdel", "abdul", "abdal", "abdu"})
_LATIN_ARTICLES = frozenset({"el", "al", "ul"})
_LATIN_CLUSTERS: dict[str, str] = {
    variant: canonical
    for canonical, variants in {
        "mohamed": ("mohamad", "muhamad", "muhamed"),
        "ahmed": ("ahmad",),
        "mahmoud": ("mahmod", "mahmud"),
        "yousef": ("yosef", "yusef", "yusuf", "yousif"),
        "khaled": ("khalid",),
        "fatma": ("fatima",),
        "nour": ("nor", "nur"),
    }.items()
    for variant in variants
}
_PHONE_SEPARATORS = re.compile(r"[\s\-.()]")
_E164_EG_MOBILE = re.compile(r"\+201[0125][0-9]{8}")


def strip_invisible(text: str) -> str:
    """Remove bidi marks and embeddings, ZWNJ/ZWJ, the Arabic letter mark and BOM."""
    return text.translate(_INVISIBLE)


def ascii_digits(text: str) -> str:
    """Arabic-Indic and Persian digits to ASCII."""
    return text.translate(_DIGITS)


def has_arabic(text: str) -> bool:
    return _ARABIC_CHAR.search(text) is not None


def _base(text: str) -> str:
    return ascii_digits(strip_invisible(unicodedata.normalize("NFKC", text)))


def _fold_arabic_chars(text: str) -> str:
    return _TASHKEEL.sub("", text).translate(_ARABIC_LETTERS)


def fold_arabic(text: str) -> str:
    """Arabic-script folding; whitespace collapsed to single spaces, «عبد X» joined."""
    folded = " ".join(_fold_arabic_chars(_base(text)).split())
    return _ABD_JOIN.sub(_ABD, folded)


def _latin_chars(token: str) -> str:
    decomposed = unicodedata.normalize("NFKD", token.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _fold_latin_token(token: str) -> str:
    token = _DOUBLED.sub(r"\1", token)
    if m := _ABD_LATIN.fullmatch(token):
        token = "abdel" + m.group(1)
    return _LATIN_CLUSTERS.get(token, token)


def _raw_tokens(text: str) -> list[str]:
    cleaned = []
    for char in _base(text):
        if char == "-":
            continue  # hyphens join: "Abdel-Halim" is one token
        category = unicodedata.category(char)
        cleaned.append(char if category[0] in "LMN" else " ")
    return "".join(cleaned).split()


def _merge_latin(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _LATIN_ABD_PARTICLES and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt in _LATIN_ARTICLES and i + 2 < len(tokens):
                merged.append(token + "el" + tokens[i + 2])
                i += 3
            else:
                merged.append(token + nxt)
                i += 2
        elif token in _LATIN_ARTICLES and i + 1 < len(tokens):
            merged.append("el" + tokens[i + 1])
            i += 2
        else:
            merged.append(token)
            i += 1
    return merged


def name_tokens(text: str) -> list[str]:
    """Folded name tokens, each folded in its own script, with compound particles joined."""
    tokens: list[str] = []
    latin_run: list[str] = []

    def flush() -> None:
        tokens.extend(_fold_latin_token(t) for t in _merge_latin(latin_run))
        latin_run.clear()

    pending_abd = False
    for raw in _raw_tokens(text):
        if has_arabic(raw):
            flush()
            folded = _fold_arabic_chars(raw)
            if pending_abd:
                tokens[-1] += folded
                pending_abd = False
            else:
                tokens.append(folded)
                pending_abd = folded == _ABD
        else:
            pending_abd = False
            latin_run.append(_latin_chars(raw))
    flush()
    return [t for t in tokens if t]


def name_key(text: str) -> str:
    """Space-insensitive folded key of a name in any script."""
    return "".join(name_tokens(text))


def fold_latin(text: str) -> str:
    """Latin folding of a romanised name: one lowercase key without spaces or hyphens."""
    return "".join(
        _fold_latin_token(t) for t in _merge_latin([_latin_chars(t) for t in _raw_tokens(text)])
    )


def normalise_phone(text: str) -> str | None:
    """E.164 for an Egyptian mobile written as 010…, +20 10…, 0020 10…, 20 10… or 010-1234-5678.

    Arabic-Indic digits, spaces, hyphens, dots, brackets and bidi marks are accepted. Anything
    that is not then `+201[0125]` plus eight digits (a landline, a 10-digit number) is `None`.
    """
    s = _PHONE_SEPARATORS.sub("", _base(text))
    if s.startswith("+"):
        candidate = s
    elif s.startswith("00"):
        candidate = "+" + s[2:]
    elif s.startswith("20") and len(s) == 12:
        candidate = "+" + s
    elif s.startswith("0") and len(s) == 11:
        candidate = "+20" + s[1:]
    else:
        return None
    return candidate if _E164_EG_MOBILE.fullmatch(candidate) else None


class Named(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def aliases(self) -> Sequence[str]: ...


class Identity(Named, Protocol):
    @property
    def phone(self) -> str | None: ...


class NotFound(TypedDict):
    error: Literal["not_found"]


class Ambiguous(TypedDict):
    ambiguous: list[str]


type LookupResult = str | NotFound | Ambiguous


def _forms(record: Named) -> list[list[str]]:
    forms: list[list[str]] = []
    for text in (record.name, *record.aliases):
        tokens = name_tokens(text)
        if tokens and tokens not in forms:
            forms.append(tokens)
    return forms


def _query_matches(query: list[str], record: Named) -> bool:
    key = "".join(query)
    return any("".join(form) == key or form[: len(query)] == query for form in _forms(record))


def name_matches(record: Named, query: str) -> bool:
    """Does a name with at least two folded tokens match the record's name or an alias?"""
    tokens = name_tokens(query)
    return len(tokens) >= MIN_NAME_TOKENS and _query_matches(tokens, record)


def phone_matches(record: Identity, phone: str) -> bool:
    wanted = normalise_phone(phone)
    return (
        wanted is not None and record.phone is not None and normalise_phone(record.phone) == wanted
    )


def match_name(records: Iterable[Named], query: str) -> list[str]:
    """Sorted ids of the records the name matches (empty for fewer than two tokens)."""
    tokens = name_tokens(query)
    if len(tokens) < MIN_NAME_TOKENS:
        return []
    return sorted({r.id for r in records if _query_matches(tokens, r)})


def match_phone(records: Iterable[Identity], phone: str) -> list[str]:
    """Sorted ids of the records whose phone equals the normalised phone."""
    return sorted({r.id for r in records if phone_matches(r, phone)})


def _single(ids: list[str]) -> str | Ambiguous:
    return ids[0] if len(ids) == 1 else {"ambiguous": ids}


def lookup(
    records: Sequence[Identity], *, name: str | None = None, phone: str | None = None
) -> LookupResult:
    """Phone first, then folded name: one id, `{"error": "not_found"}` or `{"ambiguous": ids}`."""
    if phone:
        hits = match_phone(records, phone)
        if hits:
            return _single(hits)
    if name:
        hits = match_name(records, name)
        if hits:
            return _single(hits)
    return {"error": "not_found"}


@dataclass(frozen=True, order=True)
class Collision:
    kind: Literal["name", "phone"]
    key: str
    ids: tuple[str, ...]


def alias_collisions(records: Sequence[Named]) -> list[Collision]:
    """Names or aliases of one record that the lookup would also match on another record."""
    found: set[Collision] = set()
    for record in records:
        for text in (record.name, *record.aliases):
            hits = match_name(records, text)
            if len(hits) > 1:
                found.add(Collision("name", name_key(text), tuple(hits)))
    return sorted(found)


def phone_collisions(records: Sequence[Identity]) -> list[Collision]:
    """Records sharing a phone after normalisation."""
    by_phone: dict[str, set[str]] = {}
    for record in records:
        phone = normalise_phone(record.phone) if record.phone else None
        if phone is not None:
            by_phone.setdefault(phone, set()).add(record.id)
    return sorted(
        Collision("phone", phone, tuple(sorted(ids)))
        for phone, ids in by_phone.items()
        if len(ids) > 1
    )


def unmatchable_aliases(records: Sequence[Named]) -> list[tuple[str, str]]:
    """(id, alias) pairs the lookup can never match: fewer than two folded tokens."""
    return [
        (record.id, text)
        for record in records
        for text in (record.name, *record.aliases)
        if len(name_tokens(text)) < MIN_NAME_TOKENS
    ]
