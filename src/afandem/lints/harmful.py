"""Harmful-text lint (docs/dataset-spec.md §2, Harmful items and the lint table).

- Every item, every text (text, follow-up, confirm and the Arabizi variant): no term from the
  forbidden-topic lists in `lexicons/harmful.json` (self-harm, violence, life-threatening
  emergencies, in Arabic script, Arabizi and English), matched whole-word and clitic-aware
  after folding; an Arabic term also matches with the article. A topic's `error` terms are
  errors; its `warning` terms have an innocent reading in a clinic or bank request (a medical
  complaint, a name, a common hyperbole) and are warnings to look at. Phrases in `exempt` (the
  non-emergency hyperbole idioms quoted in the spec for the lexicon controls) are masked first,
  and no list holds those idioms' own words (the bare 'kill' and 'die' verbs), so "my tooth is
  killing me" passes while "kill myself" or a named emergency does not.
- `refuse` items only, on the text: at most one sentence of pretext beside the request, read as
  at most `max_refuse_sentences` sentences of `sentence_min_words` words or more (a warning:
  sentence splitting is a heuristic); and no steps: two or more enumerated lines or numbered
  items are an error, a step word (`step_words`) a warning.
"""

import re
from collections.abc import Iterator

from afandem.lints import lexicons
from afandem.lints.egyptian import quote
from afandem.lints.findings import Finding, Severity
from afandem.lints.text import ALEF_LAM, Phrase, find_phrase, fold, is_arabic, tokens
from afandem.scenarios.schema import Scenario

RULE = "harmful_text"
TOPIC_LABELS = {"self_harm": "self-harm", "violence": "violence", "emergency": "emergency"}
MIN_STEPS = 2

_DIGIT = "[0-9\N{ARABIC-INDIC DIGIT ZERO}-\N{ARABIC-INDIC DIGIT NINE}]"
_SENTENCE_END = re.compile(
    # a full stop after a word of three or more characters (so not 'Dr.' or a one-letter
    # abbreviation), or any question mark, exclamation mark, ellipsis or line break
    r"(?<=[^\s.]{3})\.+(?=\s|$)"
    "|[!?\N{ARABIC QUESTION MARK}\N{ARABIC FULL STOP}\N{HORIZONTAL ELLIPSIS}\n]+"
)
_ENUMERATED_LINE = re.compile(
    r"^[ \t]*(?:" + _DIGIT + r"{1,2}[.)\-:]|[-*\N{BULLET}])[ \t]+", re.MULTILINE
)
_NUMBERED_ITEM = re.compile(r"(?:^|(?<=\s))\(?" + _DIGIT + r"{1,2}\)[ \t]")

type Hit = tuple[str, Severity, str]
"""(topic, severity, lexicon term as written)."""


def _with_article(form: Phrase) -> list[Phrase]:
    """The folded term, and for an Arabic term without the article, the term with it."""
    if is_arabic(form[0]) and not form[0].startswith(ALEF_LAM):
        return [form, (ALEF_LAM + form[0], *form[1:])]
    return [form]


def _exempt_positions(toks: list[str]) -> set[int]:
    masked: set[int] = set()
    for _, form in lexicons.phrases(lexicons.harmful().exempt):
        for start in find_phrase(toks, form):
            masked.update(range(start, start + len(form)))
    return masked


def _found(toks: list[str], form: Phrase, masked: set[int]) -> bool:
    return any(
        masked.isdisjoint(range(start, start + len(variant)))
        for variant in _with_article(form)
        for start in find_phrase(toks, variant)
    )


def topic_hits(text: str) -> list[Hit]:
    """Every forbidden-topic term in a text, outside the exempt idioms."""
    toks = tokens(fold(text))
    masked = _exempt_positions(toks)
    hits: list[Hit] = []
    for topic, terms in lexicons.harmful().topics.items():
        tiers: tuple[tuple[Severity, list[str]], ...] = (
            ("error", terms.error),
            ("warning", terms.warning),
        )
        for severity, forms in tiers:
            hits.extend(
                (topic, severity, shown)
                for shown, form in lexicons.phrases(forms)
                if _found(toks, form, masked)
            )
    return hits


def sentences(text: str) -> list[str]:
    """The sentences of a text that have `sentence_min_words` words or more (digit runs such as
    a phone number are not words, so a name-and-phone fragment is not a sentence)."""
    least = lexicons.harmful().sentence_min_words
    found: list[str] = []
    for part in _SENTENCE_END.split(text):
        words = [token for token in tokens(fold(part)) if not token.isdigit()]
        if len(words) >= least:
            found.append(part.strip())
    return found


def enumerated_items(text: str) -> int:
    """Enumerated lines ('1.', '2)', '-', a bullet) or inline numbered items ('1) ... 2) ...')."""
    return max(len(_ENUMERATED_LINE.findall(text)), len(_NUMBERED_ITEM.findall(text)))


def step_words(text: str) -> list[str]:
    toks = tokens(fold(text))
    return [
        shown
        for shown, form in lexicons.phrases(lexicons.harmful().step_words)
        if find_phrase(toks, form)
    ]


def _texts(scenario: Scenario) -> Iterator[tuple[str, str, str]]:
    for name, block in scenario.texts.columns():
        for field, text in block.fields_with_text():
            yield name, field, text
    if scenario.arabizi_variant is not None:
        yield "arabizi_variant", "text", scenario.arabizi_variant.text


def _topic_findings(column: str, field: str, text: str) -> list[Finding]:
    grouped: dict[tuple[str, Severity], list[str]] = {}
    for topic, severity, shown in topic_hits(text):
        grouped.setdefault((topic, severity), []).append(shown)
    findings: list[Finding] = []
    for (topic, severity), terms in grouped.items():
        label = TOPIC_LABELS.get(topic, topic)
        if severity == "error":
            message = (
                f"{label} term {quote(terms)}: no self-harm, violence or life-threatening "
                "emergency in any text; if this use is a non-emergency idiom, add it to "
                "`exempt` in src/afandem/lints/lexicons/harmful.json"
            )
        else:
            message = (
                f"possible {label} term {quote(terms)}: check that the text is not about "
                "self-harm, violence or a life-threatening emergency"
            )
        findings.append(Finding(RULE, message, column=column, field=field, severity=severity))
    return findings


def _refuse_findings(column: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    most = lexicons.harmful().max_refuse_sentences
    found = len(sentences(text))
    if found > most:
        message = (
            f"{found} sentences: a refuse text is the request plus at most one sentence of "
            "pretext (a heuristic count; check)"
        )
        findings.append(Finding(RULE, message, column=column, field="text", severity="warning"))
    items = enumerated_items(text)
    if items >= MIN_STEPS:
        message = f"{items} enumerated items: a refuse text is intent-level, with no steps"
        findings.append(Finding(RULE, message, column=column, field="text"))
    words = step_words(text)
    if words:
        message = f"step word(s) {quote(words)}: a refuse text is intent-level, with no steps"
        findings.append(Finding(RULE, message, column=column, field="text", severity="warning"))
    return findings


def check_harmful_text(scenario: Scenario) -> list[Finding]:
    findings: list[Finding] = []
    for column, field, text in _texts(scenario):
        findings.extend(_topic_findings(column, field, text))
        if scenario.behaviour == "refuse" and field == "text":
            findings.extend(_refuse_findings(column, text))
    return findings
