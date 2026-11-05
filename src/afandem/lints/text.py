"""Text normalisation for the lints: folding, digits, tokens and clitic-aware matching.

Arabic characters are written as named escapes so the source holds no RTL or invisible
characters; the word lists themselves live in `lexicons/*.json`.

Folding follows docs/harness-spec.md §8: NFKC; tatweel, ZWNJ/ZWJ and bidi marks removed;
tashkeel removed; alef with hamza/madda and alef wasla to bare alef, alef maqsura to ya,
ta marbuta to ha, Persian ya/kaf to Arabic; Arabic-Indic and Persian digits to ASCII; Latin
casefolded. `light_fold` does the same but keeps the letter shapes (hamza seats, ta
marbuta, alef maqsura) for the checks that need them.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence

Phrase = tuple[str, ...]

_INDIC_DIGITS = str.maketrans(
    {
        **{chr(0x0660 + n): str(n) for n in range(10)},  # Arabic-Indic
        **{chr(0x06F0 + n): str(n) for n in range(10)},  # Extended (Persian)
    }
)
_INVISIBLE = re.compile(
    "[\N{ARABIC TATWEEL}\N{ARABIC LETTER MARK}"
    "\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}"
    "\N{LEFT-TO-RIGHT MARK}\N{RIGHT-TO-LEFT MARK}"
    "\N{LEFT-TO-RIGHT EMBEDDING}-\N{RIGHT-TO-LEFT OVERRIDE}"
    "\N{LEFT-TO-RIGHT ISOLATE}-\N{POP DIRECTIONAL ISOLATE}]"
)
_DIACRITICS = re.compile(
    "[\N{ARABIC FATHATAN}-\N{ARABIC WAVY HAMZA BELOW}"
    "\N{ARABIC LETTER SUPERSCRIPT ALEF}"
    "\N{ARABIC SMALL HIGH LIGATURE SAD WITH LAM WITH ALEF MAKSURA}-\N{ARABIC SMALL LOW MEEM}]"
)
ALEF = "\N{ARABIC LETTER ALEF}"
LAM = "\N{ARABIC LETTER LAM}"
ALEF_LAM = ALEF + LAM
_LETTER_FOLD = str.maketrans(
    {
        "\N{ARABIC LETTER ALEF WITH HAMZA ABOVE}": ALEF,
        "\N{ARABIC LETTER ALEF WITH HAMZA BELOW}": ALEF,
        "\N{ARABIC LETTER ALEF WITH MADDA ABOVE}": ALEF,
        "\N{ARABIC LETTER ALEF WASLA}": ALEF,
        "\N{ARABIC LETTER ALEF MAKSURA}": "\N{ARABIC LETTER YEH}",
        "\N{ARABIC LETTER FARSI YEH}": "\N{ARABIC LETTER YEH}",
        "\N{ARABIC LETTER TEH MARBUTA}": "\N{ARABIC LETTER HEH}",
        "\N{ARABIC LETTER KEHEH}": "\N{ARABIC LETTER KAF}",
    }
)
ARABIC_LETTERS = (
    "\N{ARABIC LETTER HAMZA}-\N{ARABIC LETTER GHAIN}"
    "\N{ARABIC LETTER FEH}-\N{ARABIC LETTER YEH}"
    "\N{ARABIC LETTER ALEF WASLA}-\N{ARABIC LETTER YEH BARREE WITH HAMZA ABOVE}"
    "\N{ARABIC LETTER AE}"
    "\N{ARABIC LETTER SHEEN WITH DOT BELOW}-\N{ARABIC LETTER HEH WITH INVERTED V}"
)
_ARABIC_LETTER = re.compile(f"[{ARABIC_LETTERS}]")
_TOKEN = re.compile(f"[{ARABIC_LETTERS}]+|[a-z0-9]+")
_ARABIC_INDIC_DIGIT = re.compile(
    "[\N{ARABIC-INDIC DIGIT ZERO}-\N{ARABIC-INDIC DIGIT NINE}"
    "\N{EXTENDED ARABIC-INDIC DIGIT ZERO}-\N{EXTENDED ARABIC-INDIC DIGIT NINE}]"
)
_ASCII_DIGIT = re.compile("[0-9]")
_CS_ARTICLE = re.compile(ALEF_LAM + "\N{ARABIC TATWEEL}*[ \t]*(?=[A-Za-z])")
_ABD = "\N{ARABIC LETTER AIN}\N{ARABIC LETTER BEH}\N{ARABIC LETTER DAL}"
_ABD_SPACE = re.compile(f"(?<![{ARABIC_LETTERS}])({_ABD})\\s+(?=[{ARABIC_LETTERS}])")

CONJUNCTIONS = ("\N{ARABIC LETTER WAW}", "\N{ARABIC LETTER FEH}")  # wa-, fa-
PREPOSITIONS = ("\N{ARABIC LETTER BEH}", LAM, "\N{ARABIC LETTER KAF}")  # bi-, li-, ka-


def ascii_digits(text: str) -> str:
    """Arabic-Indic and Persian digits to ASCII."""
    return text.translate(_INDIC_DIGITS)


def light_fold(text: str) -> str:
    """NFKC, invisible marks and diacritics removed, ASCII digits, casefolded Latin."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = _DIACRITICS.sub("", text)
    return ascii_digits(text).casefold()


def fold(text: str) -> str:
    """`light_fold` plus the Arabic letter folding used for matching."""
    return light_fold(text).translate(_LETTER_FOLD)


def fold_name(text: str) -> str:
    """`fold` plus 'abd + name' written with or without the space (Abd El Rahman)."""
    return _ABD_SPACE.sub(r"\1", fold(text))


def tokens(folded: str) -> list[str]:
    """Arabic-letter runs and ASCII alphanumeric runs of an already folded text."""
    return _TOKEN.findall(folded)


def phrase(text: str, *, light: bool = False) -> Phrase:
    """The folded token tuple of a lexicon entry or a text."""
    return tuple(tokens(light_fold(text) if light else fold(text)))


def is_arabic(token: str) -> bool:
    return bool(_ARABIC_LETTER.match(token))


def has_arabic_letters(text: str) -> bool:
    return bool(_ARABIC_LETTER.search(text))


def has_arabic_indic_digits(text: str) -> bool:
    return bool(_ARABIC_INDIC_DIGIT.search(text))


def has_ascii_digits(text: str) -> bool:
    return bool(_ASCII_DIGIT.search(text))


def words_with_diacritics(text: str) -> list[str]:
    """Whitespace-separated words that carry tashkeel or Quranic marks (after NFC)."""
    text = unicodedata.normalize("NFC", text)
    return [word for word in text.split() if _DIACRITICS.search(word)]


def normalise_cs_articles(text: str) -> str:
    """The three accepted CS article forms (article attached to the English word, with a
    tatweel, or with a space) become the default: article, space, word."""
    return _CS_ARTICLE.sub(ALEF_LAM + " ", text)


def whitespace_tokens(text: str) -> int:
    return len(text.split())


def _proclitic_variants(form: str) -> set[str]:
    """Spellings of `form` behind proclitics: wa/fa, bi/li/ka (optionally after wa/fa), and
    li + article assimilated to a double lam."""
    variants: set[str] = set()
    for conj in ("", *CONJUNCTIONS):
        if conj:
            variants.add(conj + form)
        variants.update(conj + prep + form for prep in PREPOSITIONS)
        if form.startswith(ALEF_LAM):
            variants.add(conj + LAM + form[1:])
    return variants


def arabic_matches(token: str, form: str, *, proclitics: bool = True) -> bool:
    """Whole-word match of a folded Arabic token against a folded form.

    With `proclitics`, the form may also carry wa-/fa-, bi-/li-/ka- (after an optional
    wa-/fa-), or li- merged with its article. Forms of one or two letters accept only wa-,
    so a two-letter MSA-ism never matches longer words that merely end in it. Enclitics are
    never stripped: the spec says whole-word matching lets a suffixed preposition pass.
    """
    if token == form:
        return True
    if not proclitics or not form:
        return False
    if len(form) <= 2:
        return token == CONJUNCTIONS[0] + form
    return token in _proclitic_variants(form)


def token_matches(token: str, form: str, *, proclitics: bool = True) -> bool:
    if is_arabic(form):
        return arabic_matches(token, form, proclitics=proclitics)
    return token == form


def find_phrase(
    text_tokens: Sequence[str], target: Phrase, *, proclitics: bool = True
) -> list[int]:
    """Start indices where `target` occurs; only its first token may carry proclitics."""
    if not target or len(target) > len(text_tokens):
        return []
    hits: list[int] = []
    for start in range(len(text_tokens) - len(target) + 1):
        if not token_matches(text_tokens[start], target[0], proclitics=proclitics):
            continue
        if all(text_tokens[start + i] == target[i] for i in range(1, len(target))):
            hits.append(start)
    return hits


def contains_phrase(text_tokens: Sequence[str], target: Phrase, *, proclitics: bool = True) -> bool:
    return bool(find_phrase(text_tokens, target, proclitics=proclitics))


def matched_forms(
    text_tokens: Sequence[str], forms: Iterable[Phrase], *, proclitics: bool = True
) -> list[Phrase]:
    """The forms (in lexicon order) that occur in the token list."""
    return [form for form in forms if contains_phrase(text_tokens, form, proclitics=proclitics)]
