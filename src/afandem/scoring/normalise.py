"""Normalisers, `normaliser_version` 1 (docs/harness-spec.md §8, docs/methodology.md §3).

Everything that compares a model's words or arguments with an authored value goes through here:
argument accuracy and tool selection (`normalise_arg`), `inform` answers (`answer_found`), and
the phone validity flags. Pure functions; the word lists live in `lexicons/*.json` (time, money)
and in the lints' `numbers.json` and `dates.json` (number words, months, relative days).
Folding reuses `afandem.sandbox.names` (the lookup's Arabic and Latin folding) and
`afandem.lints.text` (whole-word matching with Arabic proclitics), so the scorer, the sandbox
and the lints read text the same way.

- **Digits.** Arabic-Indic and Persian digits become ASCII; `has_non_ascii_digits` is computed
  on the raw text first (`int("٣")` succeeds, so the flag would otherwise be lost).
- **Marks.** RTL/LTR marks, embeddings, isolates, ZWNJ/ZWJ and the BOM are stripped (`clean`).
- **Numbers.** Thousands separators `,`, «٬» and `.` (the dot only with groups of three and a
  value of at least 1,000, so `12.5` stays a decimal); decimal `.` and «٫»; `2k` = 2000; the
  number-word lexicon («ألف وربع» = 1250, longest form first).
- **Money.** A number plus currency markers (ج.م, LE, EGP, «جنيه»; «جنية» folds to «جنيه»);
  «جنيه ونص» adds a half. Integer EGP when the amount is whole.
- **Dates** are dates: ISO, D/M[/Y] (DD/MM, the policy block's convention; year from `now`),
  day + month name or «شهر» + number, relative days from `now` («بكرة», «بعد غد», 'the day
  after tomorrow'); `parse_date` also reads a weekday name as its next occurrence (1-7 days).
- **Times** become `HH:MM` through the time lexicon (`lexicons/time.json`): digits (`6:30`,
  `5 pm`, «٥:٠٠ م»), hour words with minute words («تلاتة ونص», «خمسة إلا ربع», 'half past
  six') and period words («الضهر», «العصر», «بليل»); without a period the opening hours decide
  between the a.m. and p.m. reading. A period word alone is a window (`period_window`).
- **Phones** become E.164 from the five Egyptian forms (`010…`, `+20 10…`, `0020 10…`,
  `20 10…`, `010-1234-5678`); anything that is not then `^\\+201[0125][0-9]{8}$` is flagged.
- **Text** is folded (NFKC, tashkeel, tatweel, ZWNJ, ة→ه, ى→ي, أإآ→ا, Persian ی/ک, «عبد X»
  joined; Latin casefolded, accents dropped, doubled letters collapsed, el/al particles joined)
  and compared as whole-word token sequences; no automatic Arabizi transliteration of names
  (scenarios list the variants as `forms` or aliases).
"""

import datetime as dt
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from afandem.lints import lexicons as lint_lexicons
from afandem.lints.text import Phrase, find_phrase, fold, phrase, token_matches, tokens
from afandem.sandbox.names import (
    ascii_digits,
    fold_arabic,
    name_tokens,
    normalise_phone,
    strip_invisible,
)
from afandem.scenarios.schema import WEEKDAYS
from afandem.scoring import lexicons

NORMALISER_VERSION: Final = "2"

type Number = int | float

E164_EG_MOBILE: Final = re.compile(r"^\+201[0125][0-9]{8}$")
ISO_DATE: Final = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}")
HHMM: Final = re.compile(r"^([01]?[0-9]|2[0-3])[:.]([0-5][0-9])(?::[0-5][0-9])?$")

# ---------------------------------------------------------------- characters


def has_non_ascii_digits(text: str) -> bool:
    """Any decimal digit outside 0-9 (Arabic-Indic, Persian, ...), checked on the raw text."""
    return any(unicodedata.category(c) == "Nd" and not "0" <= c <= "9" for c in text)


def clean(text: str) -> str:
    """NFKC, bidi and zero-width marks stripped, Arabic-Indic and Persian digits to ASCII."""
    return ascii_digits(strip_invisible(unicodedata.normalize("NFKC", text)))


def fold_text(text: str) -> str:
    """Arabic folding (as the identity lookup) plus Latin casefold, whitespace collapsed."""
    return " ".join(fold_arabic(text).casefold().split())


def text_tokens(text: str) -> list[str]:
    """Folded tokens in each token's own script (`afandem.sandbox.names.name_tokens`)."""
    return name_tokens(text)


# ---------------------------------------------------------------- numbers and money

_DECIMAL_SEP = str.maketrans(
    {"\N{ARABIC DECIMAL SEPARATOR}": ".", "\N{ARABIC THOUSANDS SEPARATOR}": ","}
)
_NUMBER_RUN = re.compile(r"(?<![0-9])[0-9](?:[0-9]|[,.](?=[0-9]))*")
_COMMA_THOUSANDS = re.compile(r"^[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?$")
_DOT_THOUSANDS = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{3})+$")
_DECIMAL = re.compile(r"^[0-9]+\.[0-9]+$")
_INTEGER = re.compile(r"^[0-9]+$")


def _as_number(value: float) -> Number:
    return int(value) if float(value).is_integer() else value


def _run_value(run: str) -> Number | None:
    if _INTEGER.match(run):
        return int(run)
    if _COMMA_THOUSANDS.match(run):
        return _as_number(float(run.replace(",", "")))
    if _DOT_THOUSANDS.match(run) and int(run.replace(".", "")) >= 1000:
        return int(run.replace(".", ""))
    if _DECIMAL.match(run):
        return _as_number(float(run))
    return None


@dataclass(frozen=True, slots=True)
class _Hit:
    start: int
    value: Number


_LATIN_WORD = re.compile(r"[A-Za-z]+")


def _digit_numbers(text: str) -> list[_Hit]:
    """Digit numbers; a digit inside a Latin word is an Arabizi letter (`rob3`, `5amsa`), not a
    number, unless the letters after it are a unit (`2k`, `5pm`, `3rd`)."""
    text = clean(text).translate(_DECIMAL_SEP)
    hits: list[_Hit] = []
    suffixes = tuple(lexicons.money().thousands_suffix)
    units = set(lexicons.reply_language().unit_suffixes)
    for match in _NUMBER_RUN.finditer(text):
        before = text[match.start() - 1] if match.start() else ""
        word = _LATIN_WORD.match(text, match.end())
        if (before.isascii() and before.isalpha()) or (
            word is not None and word.group().casefold() not in units
        ):
            continue
        value = _run_value(match.group())
        if value is None:
            continue
        tail = text[match.end() : match.end() + 2].casefold()
        if tail[:1] in suffixes and not tail[1:2].isalpha():
            value = _as_number(value * 1000)
        hits.append(_Hit(match.start(), value))
    return hits


@cache
def _number_word_forms() -> tuple[tuple[Phrase, int], ...]:
    forms = [(phrase(form), value) for form, value in lint_lexicons.numbers().forms.items()]
    return tuple(sorted(((p, v) for p, v in forms if p), key=lambda item: -len(item[0])))


def _word_numbers(toks: Sequence[str]) -> list[tuple[int, int, int]]:
    """(start token, end token, value) of number words, longest form first, no overlaps."""
    found: list[tuple[int, int, int]] = []
    index = 0
    while index < len(toks):
        for form, value in _number_word_forms():
            end = index + len(form)
            if (
                end <= len(toks)
                and token_matches(toks[index], form[0])
                and list(toks[index + 1 : end]) == list(form[1:])
            ):
                found.append((index, end, value))
                index = end
                break
        else:
            index += 1
    return found


def find_numbers(text: str) -> list[Number]:
    """Every number in a text: digits in either system (with separators, `2k`) and the
    number-word lexicon."""
    values: list[Number] = [hit.value for hit in _digit_numbers(text)]
    values += [value for _, _, value in _word_numbers(tokens(fold(text)))]
    return values


def parse_number(text: str) -> Number | None:
    """The first number in a text, or None."""
    found = find_numbers(text)
    return found[0] if found else None


@cache
def _half_forms() -> tuple[Phrase, ...]:
    return tuple(p for p in (phrase(form) for form in lexicons.money().half) if p)


@cache
def _currency_forms() -> tuple[Phrase, ...]:
    return tuple(p for p in (phrase(form) for form in lexicons.money().currency) if p)


def has_currency(text: str) -> bool:
    toks = tokens(fold(text))
    return "£" in text or any(
        find_phrase(toks, form, proclitics=False) for form in _currency_forms()
    )


def parse_money(text: str) -> Number | None:
    """An amount in EGP: the first number, plus a half for «جنيه ونص»."""
    value = parse_number(text)
    if value is None:
        return None
    toks = tokens(fold(text))
    if any(find_phrase(toks, form, proclitics=False) for form in _half_forms()) and has_currency(
        text
    ):
        return _as_number(value + 0.5)
    return value


# ---------------------------------------------------------------- dates

_ISO_IN_TEXT = re.compile(r"(?<![0-9])([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})(?![0-9])")
_DMY = re.compile(
    r"(?<![0-9/.\-])([0-9]{1,2})\s*([/\-])\s*([0-9]{1,2})(?:\s*\2\s*([0-9]{4}|[0-9]{2}))?(?![0-9/])"
)
_DMY_DOTS = re.compile(r"(?<![0-9.])([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{4}|[0-9]{2})(?![0-9])")
_ORDINAL = re.compile(r"^([0-9]{1,2})(?:st|nd|rd|th)?$")


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _year(raw: str | None, now: dt.date) -> int:
    if not raw:
        return now.year
    value = int(raw)
    return value + 2000 if value < 100 else value


@cache
def _month_names() -> tuple[tuple[str, int], ...]:
    names: list[tuple[str, int]] = []
    for month, forms in lint_lexicons.dates().months.items():
        for form in forms:
            folded = phrase(form)
            if len(folded) == 1:
                names.append((folded[0], month))
    return tuple(names)


def _month_of(token: str) -> int | None:
    for name, month in _month_names():
        if token_matches(token, name):
            return month
    return None


def _day_month_dates(toks: Sequence[str], now: dt.date) -> list[dt.date]:
    """Day + month name ('8 Nov', «٨ نوفمبر», 'November 8th') or day + «شهر» + month."""
    month_words = {phrase(w)[0] for w in lint_lexicons.dates().month_words if phrase(w)}
    found: list[dt.date] = []
    for index, token in enumerate(toks):
        match = _ORDINAL.match(token)
        if match is None:
            continue
        day = int(match.group(1))
        after = toks[index + 1] if index + 1 < len(toks) else ""
        before = toks[index - 1] if index > 0 else ""
        month = _month_of(after) if after else None
        if month is None and after in month_words and index + 2 < len(toks):
            nxt = toks[index + 2]
            month = int(nxt) if nxt.isdigit() and 1 <= int(nxt) <= 12 else None
        if month is None and before:
            month = _month_of(before)
        if month is not None and (date := _safe_date(now.year, month, day)) is not None:
            found.append(date)
    return found


def _relative_dates(toks: Sequence[str], now: dt.date) -> list[dt.date]:
    lex = lint_lexicons.dates()
    blockers = {phrase(word)[0] for word in lex.relative_day_blockers}
    found: list[dt.date] = []
    for offset, forms in sorted(lex.relative_days.items()):
        for form in forms:
            folded = phrase(form)
            for start in find_phrase(toks, folded):
                blocked = start > 0 and toks[start - 1] in blockers
                if not blocked or folded[0] in blockers:
                    found.append(now + dt.timedelta(days=offset))
    return found


def find_dates(text: str, now: dt.date) -> list[dt.date]:
    """Every explicit or relative date in a text (weekday names alone are not read here)."""
    cleaned = clean(text)
    found: list[dt.date] = []
    rest = cleaned
    for match in _ISO_IN_TEXT.finditer(cleaned):
        date = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if date is not None:
            found.append(date)
    rest = _ISO_IN_TEXT.sub(" ", rest)
    for pattern in (_DMY_DOTS, _DMY):
        for match in pattern.finditer(rest):
            groups = match.groups()
            day, month = int(groups[0]), int(groups[1] if pattern is _DMY_DOTS else groups[2])
            year_raw = groups[2] if pattern is _DMY_DOTS else groups[3]
            date = _safe_date(_year(year_raw, now), month, day)
            if date is not None:
                found.append(date)
        rest = pattern.sub(" ", rest)
    toks = tokens(fold(rest))
    found += _day_month_dates(toks, now)
    found += _relative_dates(toks, now)
    return list(dict.fromkeys(found))


def _weekday_date(toks: Sequence[str], now: dt.date) -> dt.date | None:
    lex = lint_lexicons.dates()
    for index, name in enumerate(WEEKDAYS):
        forms = lex.weekdays[name]
        for form in (*forms.arabic, *forms.english, *forms.arabizi):
            if find_phrase(toks, phrase(form)):
                ahead = (index - now.weekday()) % 7 or 7
                return now + dt.timedelta(days=ahead)
    return None


def parse_date(text: str, now: dt.date) -> dt.date | None:
    """One date expression: ISO, D/M[/Y], day + month, a relative day or a weekday name."""
    found = find_dates(text, now)
    if found:
        return found[0]
    return _weekday_date(tokens(fold(text)), now)


# ---------------------------------------------------------------- times

type Hours = Sequence[tuple[str, str]]
"""Opening sessions as half-open (open, close) HH:MM pairs; close <= open runs past midnight."""

_CLOCK_IN_TEXT = re.compile(r"(?<![0-9])([0-9]{1,2})[:.]([0-5][0-9])(?![0-9])")
_CLOCK_TOKEN = re.compile(r"^zz([0-9]+)h([0-9]+)$")
_LATIN_PERIOD_GLUE = re.compile(r"([0-9])(am|pm)\b")
_ARABIC_PERIOD_GLUE = re.compile(
    "([0-9])(\N{ARABIC LETTER SAD}|\N{ARABIC LETTER MEEM})"
    "(?![\N{ARABIC LETTER HAMZA}-\N{ARABIC LETTER YEH}])"
)


@dataclass(frozen=True, slots=True)
class _TimeLex:
    hours: tuple[tuple[Phrase, int], ...]
    after: tuple[tuple[Phrase, int], ...]
    before: tuple[tuple[Phrase, int], ...]
    periods: tuple[tuple[Phrase, str, tuple[str, str]], ...]
    single: dict[str, str]
    markers: tuple[Phrase, ...]
    oclock: tuple[Phrase, ...]


def _longest_first[T](items: Iterable[tuple[Phrase, T]]) -> tuple[tuple[Phrase, T], ...]:
    return tuple(sorted((item for item in items if item[0]), key=lambda item: -len(item[0])))


@cache
def _time_lex() -> _TimeLex:
    lex = lexicons.time_words()
    return _TimeLex(
        hours=_longest_first((phrase(f), h) for h, forms in lex.hours.items() for f in forms),
        after=_longest_first((phrase(f), m) for f, m in lex.minutes_after.items()),
        before=_longest_first((phrase(f), m) for f, m in lex.minutes_before.items()),
        periods=tuple(
            sorted(
                (
                    (phrase(form), period.shift, period.window)
                    for period in lex.periods
                    for form in period.forms
                    if phrase(form)
                ),
                key=lambda item: -len(item[0]),
            )
        ),
        single={phrase(k)[0]: v for k, v in lex.single_letter_periods.items()},
        markers=tuple(p for p in (phrase(m) for m in lex.markers) if p),
        oclock=tuple(p for p in (phrase(m) for m in lex.oclock) if p),
    )


def _at(toks: Sequence[str], index: int, form: Phrase) -> bool:
    end = index + len(form)
    return end <= len(toks) and tuple(toks[index:end]) == form


def _match_list[T](
    toks: Sequence[str], index: int, forms: Iterable[tuple[Phrase, T]]
) -> tuple[int, T] | None:
    """(length, value) of the first (longest) form at `index`."""
    for form, value in forms:
        if _at(toks, index, form):
            return len(form), value
    return None


def _time_tokens(text: str) -> list[str]:
    folded = fold(text)
    folded = _CLOCK_IN_TEXT.sub(lambda m: f" zz{int(m.group(1))}h{m.group(2)} ", folded)
    folded = _LATIN_PERIOD_GLUE.sub(r"\1 \2", folded)
    folded = _ARABIC_PERIOD_GLUE.sub(r"\1 \2", folded)
    return tokens(folded)


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _inside(minute: int, hours: Hours) -> bool:
    for opening, closing in hours:
        start, end = _minutes(opening), _minutes(closing) or 24 * 60
        if start < end:
            if start <= minute < end:
                return True
        elif minute >= start or minute < end:
            return True
    return False


def _resolve(hour: int, minute: int, shift: str | None, hours: Hours | None) -> str | None:
    total = hour * 60 + minute
    if minute < 0:  # «خمسة إلا ربع»: count back from the hour
        hour, minute = divmod(total, 60)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    if shift == "am" and hour == 12:
        hour = 0
    elif (shift == "noon" and 1 <= hour <= 3) or (shift == "pm" and hour < 12):
        hour += 12
    elif shift is None and hours and 1 <= hour <= 11:
        readings = [h for h in (hour, hour + 12) if _inside(h * 60 + minute, hours)]
        if len(readings) == 1:
            hour = readings[0]
    return f"{hour % 24:02d}:{minute:02d}"


def _period_at(toks: Sequence[str], index: int) -> tuple[int, str] | None:
    lex = _time_lex()
    for form, shift, _ in lex.periods:
        if _at(toks, index, form):
            return len(form), shift
    if index < len(toks) and toks[index] in lex.single:
        return 1, lex.single[toks[index]]
    return None


def _hour_at(toks: Sequence[str], index: int) -> tuple[int, int] | None:
    """(length, hour 0-23) of a digit or word hour at `index`."""
    if index >= len(toks):
        return None
    token = toks[index]
    if token.isdigit() and len(token) <= 2 and int(token) <= 23:
        return 1, int(token)
    return _match_list(toks, index, _time_lex().hours)


def _close(
    toks: Sequence[str], start: int, end: int, clock: tuple[int, int], hours: Hours | None
) -> tuple[int, str] | None:
    """Read an optional period at `end`, resolve the clock, return (tokens used, HH:MM)."""
    period = _period_at(toks, end)
    resolved = _resolve(clock[0], clock[1], period[1] if period else None, hours)
    if resolved is None:
        return None
    return end - start + (period[0] if period else 0), resolved


def _marked(toks: Sequence[str], index: int) -> bool:
    return any(index >= len(m) and _at(toks, index - len(m), m) for m in _time_lex().markers)


def _word_time(toks: Sequence[str], index: int, hours: Hours | None) -> tuple[int, str] | None:
    """A digit or word hour with a cue: «الساعة»/'at' before it, or a minute word, 'o'clock'
    or a period after it («اتنين» alone is never a time)."""
    lex = _time_lex()
    found = _hour_at(toks, index)
    if found is None:
        return None
    end = index + found[0]
    after = _match_list(toks, end, lex.after)
    end += after[0] if after else 0
    oclock = next((len(f) for f in lex.oclock if _at(toks, end, f)), 0)
    end += oclock
    cued = after is not None or oclock or _period_at(toks, end) is not None or _marked(toks, index)
    if not cued:
        return None
    return _close(toks, index, end, (found[1], after[1] if after else 0), hours)


def _time_at(toks: Sequence[str], index: int, hours: Hours | None) -> tuple[int, str] | None:
    """(tokens used, HH:MM) of a clock time starting at `index`, or None."""
    if clock := _CLOCK_TOKEN.match(toks[index]):
        return _close(toks, index, index + 1, (int(clock.group(1)), int(clock.group(2))), hours)
    before = _match_list(toks, index, _time_lex().before)
    if before is not None:
        word = _hour_at(toks, index + before[0])
        if word is None:
            return None
        return _close(toks, index, index + before[0] + word[0], (word[1], before[1]), hours)
    return _word_time(toks, index, hours)


def find_times(text: str, hours: Hours | None = None) -> list[str]:
    """Every clock time in a text as `HH:MM` (a period word alone is a window, not a time)."""
    toks = _time_tokens(text)
    found: list[str] = []
    index = 0
    while index < len(toks):
        hit = _time_at(toks, index, hours)
        if hit is None:
            index += 1
            continue
        found.append(hit[1])
        index += max(hit[0], 1)
    return list(dict.fromkeys(found))


def parse_time(text: str, hours: Hours | None = None) -> str | None:
    """The first clock time in a text as `HH:MM`, or None; `HH:MM` itself is zero-padded."""
    if match := HHMM.match(clean(text).strip()):
        return _resolve(int(match.group(1)), int(match.group(2)), None, hours)
    found = find_times(text, hours)
    return found[0] if found else None


def period_window(text: str) -> tuple[str, str] | None:
    """The window of a period word used without a clock time («بعد الضهر» = 15:00-17:00)."""
    if find_times(text):
        return None
    toks = _time_tokens(text)
    for index in range(len(toks)):
        for form, _, window in _time_lex().periods:
            if _at(toks, index, form):
                return window
    return None


# ---------------------------------------------------------------- phones


@dataclass(frozen=True, slots=True)
class Phone:
    """A phone argument after normalisation, with its validity flags."""

    e164: str | None
    flags: tuple[str, ...]


def normalise_phone_value(raw: str) -> Phone:
    """E.164 from the five Egyptian mobile forms; flags `non_ascii_digits` (raw text),
    `not_e164` (written in another form) and `not_e164_mobile` (no Egyptian mobile at all:
    a landline, a 10-digit number)."""
    flags: list[str] = []
    if has_non_ascii_digits(raw):
        flags.append("non_ascii_digits")
    e164 = normalise_phone(raw)
    if e164 is None:
        flags.append("not_e164_mobile")
    elif not E164_EG_MOBILE.match(raw.strip()):
        flags.append("not_e164")
    return Phone(e164, tuple(flags))


_PHONE_RUN = re.compile(r"\+?[0-9][0-9\s\-.()]{7,20}[0-9]")


def find_phones(text: str) -> list[str]:
    """Every Egyptian mobile in a text, as E.164."""
    found = [normalise_phone(run) for run in _PHONE_RUN.findall(clean(text))]
    return list(dict.fromkeys(p for p in found if p is not None))


# ---------------------------------------------------------------- arguments


def _field_kind(field: str) -> str:
    name = field.casefold()
    if name == "id" or name.endswith("_id") or name.endswith("last4"):
        return "id"
    if "phone" in name:
        return "phone"
    if "date" in name:
        return "date"
    if name == "time" or name.endswith("_time"):
        return "time"
    if "amount" in name:
        return "amount"
    return "text"


def normalise_arg(field: str, value: object) -> object:
    """The comparable form of one argument value, by field name: ids exact (digits and marks
    cleaned), phones E.164, dates ISO, times HH:MM, amounts numbers, other text folded."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return _as_number(value)
    if isinstance(value, list):
        return [normalise_arg(field, item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): normalise_arg(str(k), v) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    text = clean(value).strip()
    return _BY_KIND[_field_kind(field)](text)


def _iso_or_text(text: str) -> str:
    date = (
        _safe_date(int(text[:4]), int(text[5:7]), int(text[8:10])) if ISO_DATE.match(text) else None
    )
    return date.isoformat() if date is not None else text


def _amount_or_text(text: str) -> object:
    amount = parse_money(text)
    return amount if amount is not None else fold_text(text)


_BY_KIND: Final[dict[str, Callable[[str], object]]] = {
    "id": lambda text: text,
    "phone": lambda text: normalise_phone(text) or text,
    "date": _iso_or_text,
    "time": lambda text: parse_time(text) or text,
    "amount": _amount_or_text,
    "text": fold_text,
}


def arg_matches(field: str, actual: object, wanted: object) -> bool:
    """Does `actual` equal `wanted`, or one of its acceptable values, after normalisation?"""
    options = wanted if isinstance(wanted, list) else [wanted]
    got = normalise_arg(field, actual)
    return any(got == normalise_arg(field, option) for option in options)


def normalised_args(args: Mapping[str, Any]) -> dict[str, object]:
    return {str(k): normalise_arg(str(k), v) for k, v in args.items()}


# ---------------------------------------------------------------- inform answers


def contains_form(text_toks: Sequence[str], form: str) -> bool:
    """Whole-word occurrence of a folded form; Arabic proclitics allowed on its first word."""
    target = text_tokens(form)
    if not target or len(target) > len(text_toks):
        return False
    for start in range(len(text_toks) - len(target) + 1):
        if (
            token_matches(text_toks[start], target[0])
            and list(text_toks[start + 1 : start + len(target)]) == target[1:]
        ):
            return True
    return False


def _numeric(value: str | int) -> Number | None:
    if isinstance(value, int):
        return value
    cleaned = clean(value).strip()
    return _run_value(cleaned.translate(_DECIMAL_SEP)) if cleaned else None


def value_found(
    text: str, value: str | int, *, now: dt.date | None = None, hours: Hours | None = None
) -> bool:
    """Is a normalised value present in a reply: as a number, a date, a time, a phone, or a
    folded word sequence?"""
    number = _numeric(value)
    if number is not None:
        return number in find_numbers(text)
    raw = clean(str(value)).strip()
    if now is not None and ISO_DATE.fullmatch(raw):
        return dt.date.fromisoformat(raw) in find_dates(text, now)
    if HHMM.match(raw):
        return parse_time(raw) in find_times(text, hours)
    if E164_EG_MOBILE.match(raw):
        return raw in find_phones(text)
    return contains_form(text_tokens(text), raw)


def answer_found(
    text: str,
    value: str | int,
    forms: Sequence[str],
    *,
    now: dt.date | None = None,
    hours: Hours | None = None,
) -> bool:
    """`inform` scoring: the reply holds the normalised value or one of its authored surface
    forms (any column's form: an English reply can match the Latin form)."""
    if value_found(text, value, now=now, hours=hours):
        return True
    toks = text_tokens(text)
    for form in forms:
        number = _numeric(form)
        if number is not None and number in find_numbers(text):
            return True
        if contains_form(toks, form):
            return True
    return False


__all__ = [
    "E164_EG_MOBILE",
    "NORMALISER_VERSION",
    "Hours",
    "Number",
    "Phone",
    "answer_found",
    "arg_matches",
    "clean",
    "contains_form",
    "find_dates",
    "find_numbers",
    "find_phones",
    "find_times",
    "fold_text",
    "has_currency",
    "has_non_ascii_digits",
    "normalise_arg",
    "normalise_phone_value",
    "normalised_args",
    "parse_date",
    "parse_money",
    "parse_number",
    "parse_time",
    "period_window",
    "text_tokens",
    "value_found",
]
