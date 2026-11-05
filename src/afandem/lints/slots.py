"""Slot re-extraction, the mechanical part (docs/dataset-spec.md §2, lint table).

Every slot must be present in every column in some surface form. What can be decided
mechanically is decided here: phones (E.164 against the local, +20 and 0020 forms, digits in
either numeral system, any spacing), dates (the weekday lexicon in Egyptian, MSA, Arabizi and
English, relative days such as 'tomorrow' counted from `now`, D/M numbers, day + month
name, 'day 8')
and standalone weekdays. A miss there is an error.

Everything else is confirmed when a mechanical form is found (integers as digits or as a
lexicon number word, HH:MM times, ids through the record's aliases, phone or date, enum
values verbatim) and otherwise reported once per slot as a `manual` finding naming the
columns to re-extract by hand. `intent` is always manual; `days_ahead` is derived from `now`
and the date (checked by `slot_dates`); `<slot>_weekday` rides on its date.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from afandem.lints import lexicons
from afandem.lints.context import record_names, records_with_id
from afandem.lints.findings import Finding
from afandem.lints.text import (
    Phrase,
    contains_phrase,
    find_phrase,
    fold,
    fold_name,
    phrase,
    tokens,
)
from afandem.scenarios.schema import WEEKDAYS, Scenario, SlotValue, Weekday

RULE = "slot_reextraction"
PHONE_RE = re.compile(r"^\+20([0-9]{9,10})$")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
DERIVED_SLOTS = frozenset({"days_ahead"})
WEEKDAY_SUFFIX = "_weekday"

_DIGIT_RUN = re.compile(r"\+?[0-9][0-9 \-.]*[0-9]|[0-9]")
_NUMBER = re.compile("(?<![0-9])[0-9]+(?:[,.\N{ARABIC THOUSANDS SEPARATOR}][0-9]{3})*(?![0-9])")
_THOUSANDS = re.compile(r"(?<![0-9])([0-9]+)\s?k\b")
_NUMERIC_DATE = re.compile(
    r"(?<![0-9])([0-9]{1,2})\s*[/\-.]\s*([0-9]{1,2})(?:\s*[/\-.]\s*([0-9]{2,4}))?(?![0-9])"
)
_TIME = re.compile(r"(?<![0-9])([0-9]{1,2})[:.]([0-9]{2})(?![0-9])")
_ORDINAL = re.compile(r"^([0-9]{1,2})(?:st|nd|rd|th)$")

Outcome = Literal["found", "missing", "manual", "skip"]


@dataclass(frozen=True, slots=True)
class ColumnView:
    """One column's searchable text: the text plus its follow-up."""

    name: str
    folded: str
    tokens: list[str]
    name_tokens: list[str]

    @classmethod
    def of(cls, name: str, *parts: str | None) -> "ColumnView":
        raw = "\n".join(part for part in parts if part)
        folded = fold(raw)
        return cls(name, folded, tokens(folded), tokens(fold_name(raw)))


@dataclass(frozen=True, slots=True)
class SlotContext:
    now: dt.date
    state: Mapping[str, Any]
    identity_values: frozenset[str]


def column_views(scenario: Scenario) -> list[ColumnView]:
    views = [
        ColumnView.of(name, block.text, block.follow_up) for name, block in scenario.texts.columns()
    ]
    if scenario.arabizi_variant is not None:
        views.append(ColumnView.of("arabizi_variant", scenario.arabizi_variant.text))
    return views


# --- surface forms -------------------------------------------------------------------


def phone_found(national: str, view: ColumnView) -> bool:
    """The national number (after +20) as 0…, 20… or 0020…, any spacing or digits."""
    for run in _DIGIT_RUN.findall(view.folded):
        digits = re.sub(r"[^0-9]", "", run)
        if "0" + national in digits or "20" + national in digits:
            return True
    return False


def weekday_found(weekday: Weekday, view: ColumnView) -> bool:
    lex = lexicons.dates()
    forms = lex.weekdays[weekday]
    if any(contains_phrase(view.tokens, phrase(form)) for form in forms.arabic):
        return True
    if any(contains_phrase(view.tokens, phrase(form)) for form in forms.english):
        return True
    articles = {phrase(article)[0] for article in lex.arabizi_articles}
    return any(
        _arabizi_article_phrase(view.tokens, phrase(form), articles) for form in forms.arabizi
    )


def _arabizi_article_phrase(text_tokens: list[str], form: Phrase, articles: set[str]) -> bool:
    """An Arabizi `el <stem>` form with any article, separate («lel 7ad») or attached («el7ad»)."""
    stem = form[1:] if len(form) > 1 and form[0] in articles else form
    for start in find_phrase(text_tokens, stem):
        if start > 0 and text_tokens[start - 1] in articles:
            return True
    if len(stem) == 1:
        return any(token == article + stem[0] for token in text_tokens for article in articles)
    return False


def relative_day_found(target: dt.date, view: ColumnView, now: dt.date) -> bool:
    lex = lexicons.dates()
    forms = lex.relative_days.get((target - now).days, [])
    blockers = {phrase(word)[0] for word in lex.relative_day_blockers}
    for form in forms:
        folded = phrase(form)
        for start in find_phrase(view.tokens, folded):
            blocked = start > 0 and view.tokens[start - 1] in blockers
            if not blocked or folded[0] in blockers:
                return True
    return False


def numeric_date_found(target: dt.date, view: ColumnView) -> bool:
    for day, month, year in _NUMERIC_DATE.findall(view.folded):
        if int(day) != target.day or int(month) != target.month:
            continue
        if not year or int(year) in (target.year, target.year % 100):
            return True
    return False


def _day_number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    match = _ORDINAL.match(token)
    return int(match.group(1)) if match else None


def day_month_found(target: dt.date, view: ColumnView) -> bool:
    """Day + month name or month number ('8 Nov', 'Nov 8'), an ordinal ('8th'), or a day
    word + day ('day 8'), in either numeral system."""
    lex = lexicons.dates()
    month_names = {phrase(name)[0] for name in lex.months.get(target.month, []) if phrase(name)}
    month_words = {phrase(word)[0] for word in lex.month_words}
    day_words = {phrase(word)[0] for word in lex.day_words}
    toks = view.tokens
    for index, token in enumerate(toks):
        if _day_number(token) != target.day:
            continue
        after = toks[index + 1 : index + 3]
        before = toks[index - 1] if index > 0 else ""
        if after and after[0] in month_names:
            return True
        if len(after) == 2 and after[0] in month_words and after[1] == str(target.month):
            return True
        if before in month_names or before in day_words or _ORDINAL.match(token):
            return True
    return False


def date_found(target: dt.date, view: ColumnView, now: dt.date) -> bool:
    return (
        weekday_found(WEEKDAYS[target.weekday()], view)
        or relative_day_found(target, view, now)
        or numeric_date_found(target, view)
        or day_month_found(target, view)
    )


def _numbers_in(view: ColumnView) -> set[int]:
    values = {int(re.sub(r"[^0-9]", "", match)) for match in _NUMBER.findall(view.folded)}
    values.update(int(match) * 1000 for match in _THOUSANDS.findall(view.folded))
    return values


def number_word_values(view: ColumnView) -> set[int]:
    """Values of lexicon number words; longer forms win, so 350 is not also read as 300."""
    forms = sorted(
        ((phrase(form), value) for form, value in lexicons.numbers().forms.items()),
        key=lambda item: -len(item[0]),
    )
    toks = view.tokens
    values: set[int] = set()
    index = 0
    while index < len(toks):
        for form, value in forms:
            if form and find_phrase(toks[index : index + len(form)], form):
                values.add(value)
                index += len(form)
                break
        else:
            index += 1
    return values


def integer_found(value: int, view: ColumnView) -> bool:
    return value in _numbers_in(view) or value in number_word_values(view)


def time_found(hhmm: str, view: ColumnView) -> bool:
    hour, minute = (int(part) for part in hhmm.split(":"))
    for h_text, m_text in _TIME.findall(view.folded):
        h, m = int(h_text), int(m_text)
        if m != minute:
            continue
        if h == hour or (hour > 12 and h == hour - 12) or (hour == 0 and h == 12):
            return True
    return False


def _id_outcome(value: str, view: ColumnView, ctx: SlotContext) -> Outcome:
    if value in ctx.identity_values:
        return "skip"  # the authenticated principal: implied, need not be said
    for record in records_with_id(ctx.state, value):
        if any(
            contains_phrase(view.name_tokens, phrase(fold_name(n))) for n in record_names(record)
        ):
            return "found"
        phone = record.get("phone")
        if (
            isinstance(phone, str)
            and (match := PHONE_RE.match(phone))
            and phone_found(match.group(1), view)
        ):
            return "found"
        when = record.get("date")
        if (
            isinstance(when, str)
            and ISO_DATE_RE.match(when)
            and date_found(dt.date.fromisoformat(when), view, ctx.now)
        ):
            return "found"
    return "manual"


def _string_check(value: str, view: ColumnView, ctx: SlotContext) -> tuple[bool, bool]:
    """(found, mechanical) for a string slot value that is not an id or the intent."""
    if match := PHONE_RE.match(value):
        return phone_found(match.group(1), view), True
    if ISO_DATE_RE.match(value):
        return date_found(dt.date.fromisoformat(value), view, ctx.now), True
    if value in WEEKDAYS:
        return weekday_found(value, view), True
    if TIME_RE.match(value):
        return time_found(value, view), False
    literal = phrase(value)
    return bool(literal) and contains_phrase(view.tokens, literal), False


def _string_outcome(key: str, value: str, view: ColumnView, ctx: SlotContext) -> Outcome:
    if key == "intent":
        return "manual"
    if key.endswith("_id"):
        return _id_outcome(value, view, ctx)
    found, mechanical = _string_check(value, view, ctx)
    if found:
        return "found"
    return "missing" if mechanical else "manual"


def slot_outcome(key: str, value: SlotValue, view: ColumnView, ctx: SlotContext) -> Outcome:
    if value is None or isinstance(value, bool):
        return "skip"
    if isinstance(value, list):
        outcomes = [slot_outcome(key, item, view, ctx) for item in value]
        if "found" in outcomes:
            return "found"
        return "skip" if all(outcome == "skip" for outcome in outcomes) else "manual"
    if isinstance(value, int):
        return "found" if integer_found(value, view) else "manual"
    return _string_outcome(key, value, view, ctx)


def _rides_on_date(key: str, slots: Mapping[str, SlotValue]) -> bool:
    return key.endswith(WEEKDAY_SUFFIX) and key.removesuffix(WEEKDAY_SUFFIX) in slots


def check_slots(scenario: Scenario) -> list[Finding]:
    ctx = SlotContext(
        now=scenario.now.local_date,
        state=scenario.initial_state,
        identity_values=frozenset(scenario.user_identity.values()),
    )
    views = column_views(scenario)
    findings: list[Finding] = []
    for key, value in scenario.slots.items():
        if key in DERIVED_SLOTS or _rides_on_date(key, scenario.slots):
            continue
        manual: list[str] = []
        for view in views:
            outcome = slot_outcome(key, value, view, ctx)
            if outcome == "missing":
                findings.append(
                    Finding(
                        RULE,
                        f"slot {key!r} = {value!r}: no surface form found (if the form is "
                        "legitimate, add it to src/afandem/lints/lexicons/)",
                        column=view.name,
                    )
                )
            elif outcome == "manual":
                manual.append(view.name)
        if manual:
            findings.append(
                Finding(
                    RULE,
                    f"slot {key!r} = {value!r}: not mechanically checkable in "
                    f"{', '.join(manual)}; re-extract by hand",
                    severity="manual",
                )
            )
    return findings


def _date_slots(slots: Mapping[str, SlotValue]) -> dict[str, list[dt.date]]:
    """Slots whose value is an ISO date or a list made only of ISO dates."""
    found: dict[str, list[dt.date]] = {}
    for key, value in slots.items():
        items = value if isinstance(value, list) else [value]
        parsed = [
            dt.date.fromisoformat(item)
            for item in items
            if isinstance(item, str) and ISO_DATE_RE.match(item)
        ]
        if parsed and len(parsed) == len(items):
            found[key] = parsed
    return found


def check_slot_dates(scenario: Scenario) -> list[Finding]:
    """`<slot>_weekday` matches its date, every resolved date has one, `days_ahead` agrees."""
    rule = "slot_dates"
    slots = scenario.slots
    dates = _date_slots(slots)
    findings: list[Finding] = []
    for key, parsed in dates.items():
        weekday_key = key + WEEKDAY_SUFFIX
        names: list[str] = [WEEKDAYS[day.weekday()] for day in parsed]
        expected: object = names if isinstance(slots[key], list) else names[0]
        if weekday_key not in slots:
            message = f"date slot {key!r} has no {weekday_key!r} next to it"
            findings.append(Finding(rule, message, severity="warning"))
        elif slots[weekday_key] != expected:
            message = f"{weekday_key!r} is {slots[weekday_key]!r} but {key!r} is {expected!r}"
            findings.append(Finding(rule, message))
    for key in slots:
        base = key.removesuffix(WEEKDAY_SUFFIX)
        if key.endswith(WEEKDAY_SUFFIX) and base in slots and base not in dates:
            findings.append(Finding(rule, f"{key!r} sits next to {base!r}, which is not a date"))
    days_ahead = slots.get("days_ahead")
    singles = [parsed[0] for key, parsed in dates.items() if not isinstance(slots[key], list)]
    if isinstance(days_ahead, int) and not isinstance(days_ahead, bool) and len(singles) == 1:
        actual = (singles[0] - scenario.now.local_date).days
        if actual != days_ahead:
            message = f"days_ahead is {days_ahead} but the date is {actual} days after now"
            findings.append(Finding(rule, message))
    return findings
