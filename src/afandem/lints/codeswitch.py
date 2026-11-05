"""CS insertions (docs/dataset-spec.md §2, CS and CS-Latin).

- cs and cs_latin declare 1-3 content insertions, the same ones in both columns.
- Each declared insertion occurs in its text (the three accepted article forms are
  normalised first); a discourse marker (ok, please, thanks) is never an insertion.
- An insertion containing a tool cue word (cancel, book, transfer, balance, recharge, block)
  has `tool_cue: true`.
- In cs (Arabic-script matrix) every Latin-script run that is not a discourse marker, a
  name from the state, or covered by declared insertions is an undeclared insertion; a
  multi-word run counts as one. CS-Latin's matrix is Latin, so only the declared insertions
  can be checked there.
"""

import re
import unicodedata

from afandem.lints import lexicons
from afandem.lints.context import latin_name_tokens
from afandem.lints.findings import Finding
from afandem.lints.text import Phrase, contains_phrase, normalise_cs_articles, phrase
from afandem.scenarios.schema import Column, Insertion, Scenario

RULE = "cs_insertions"
_APOSTROPHES = "'\N{RIGHT SINGLE QUOTATION MARK}"
_LATIN_RUN = re.compile(
    f"[A-Za-z][A-Za-z0-9{_APOSTROPHES}]*(?:[ \t]+[A-Za-z][A-Za-z0-9{_APOSTROPHES}]*)*"
)


def latin_runs(text: str) -> list[Phrase]:
    """Runs of Latin words separated only by spaces, as casefolded token tuples."""
    text = normalise_cs_articles(unicodedata.normalize("NFKC", text))
    return [phrase(run) for run in _LATIN_RUN.findall(text) if phrase(run)]


def _segments(run: Phrase, separators: frozenset[str]) -> list[Phrase]:
    """Split a run on discourse markers and names, dropping them."""
    parts: list[Phrase] = []
    current: list[str] = []
    for token in run:
        if token in separators:
            if current:
                parts.append(tuple(current))
            current = []
        else:
            current.append(token)
    if current:
        parts.append(tuple(current))
    return parts


def _cover(segment: Phrase, declared: list[Phrase]) -> list[Phrase]:
    """Greedy left-to-right cover of a segment by declared phrases; returns the uncovered
    stretches (each counts as one undeclared insertion)."""
    uncovered: list[Phrase] = []
    pending: list[str] = []
    index = 0
    by_length = sorted(declared, key=len, reverse=True)
    while index < len(segment):
        match = next((d for d in by_length if segment[index : index + len(d)] == d), None)
        if match is None:
            pending.append(segment[index])
            index += 1
            continue
        if pending:
            uncovered.append(tuple(pending))
            pending = []
        index += len(match)
    if pending:
        uncovered.append(tuple(pending))
    return uncovered


def _declared_problems(name: Column, items: list[Insertion], text: str) -> list[Finding]:
    lex = lexicons.code_switch()
    markers = {phrase(marker) for marker in lex.discourse_markers}
    cues = {phrase(cue)[0] for cue in lex.tool_cue_words}
    findings: list[Finding] = []
    if not lex.min_insertions <= len(items) <= lex.max_insertions:
        message = (
            f"{len(items)} declared insertions; CS needs "
            f"{lex.min_insertions}-{lex.max_insertions} content insertions"
        )
        findings.append(Finding(RULE, message, column=name, field="insertions"))
    text_tokens = [token for run in latin_runs(text) for token in (*run, "|")]
    for item in items:
        declared = phrase(item.text)
        if not declared:
            message = f"insertion {item.text!r} has no Latin-script word"
            findings.append(Finding(RULE, message, column=name, field="insertions"))
            continue
        if declared in markers:
            message = f"{item.text!r} is a discourse marker, not a content insertion"
            findings.append(Finding(RULE, message, column=name, field="insertions"))
        if not contains_phrase(text_tokens, declared):
            message = f"declared insertion {item.text!r} is not in the text"
            findings.append(Finding(RULE, message, column=name, field="insertions"))
        cue_words = sorted(cues.intersection(declared))
        if cue_words and not item.tool_cue:
            message = f"{item.text!r} names a tool ({', '.join(cue_words)}): tool_cue must be true"
            findings.append(Finding(RULE, message, column=name, field="insertions"))
    return findings


def _undeclared(scenario: Scenario) -> list[Finding]:
    lex = lexicons.code_switch()
    block = scenario.texts.cs
    separators = frozenset(
        {token for marker in lex.discourse_markers for token in phrase(marker)}
        | latin_name_tokens(scenario.initial_state)
    )
    declared = [phrase(item.text) for item in block.insertions or [] if phrase(item.text)]
    findings: list[Finding] = []
    for run in latin_runs(block.text):
        for segment in _segments(run, separators):
            for stretch in _cover(segment, declared):
                message = (
                    f"undeclared English insertion {' '.join(stretch)!r} "
                    "(declare it in insertions; it counts toward the 1-3)"
                )
                findings.append(Finding(RULE, message, column="cs", field="text"))
    return findings


def check_cs_insertions(scenario: Scenario) -> list[Finding]:
    findings: list[Finding] = []
    for name in ("cs", "cs_latin"):
        block = scenario.texts.column(name)
        findings.extend(_declared_problems(name, block.insertions or [], block.text))
    findings.extend(_undeclared(scenario))
    cs = [(phrase(i.text), i.tool_cue) for i in scenario.texts.cs.insertions or []]
    cs_latin = [(phrase(i.text), i.tool_cue) for i in scenario.texts.cs_latin.insertions or []]
    if cs != cs_latin:
        message = "cs and cs_latin must carry the same insertions (text and tool_cue, in order)"
        findings.append(Finding(RULE, message, field="insertions"))
    return findings
