"""Follow-up and confirm lexicon (docs/dataset-spec.md §2, Follow-ups and confirms).

- In the columns the spec gives a lexicon for (egy, cs, arabizi, cs_latin) a `confirm_yes`
  must contain a yes word (error) and an `ask` follow-up should (warning: it is "the answer
  plus a confirmation"); a no word in a confirm is a warning.
- 'khalas' (5alas) never appears without an unambiguous yes word, in any column.
- A period word (ba3d el dohr, bel leil...) in a follow-up makes the gold a window: every
  expected `time` argument must then be a list of at least two values.
"""

from afandem.lints import lexicons
from afandem.lints.egyptian import quote
from afandem.lints.findings import Finding, Severity
from afandem.lints.text import Phrase, contains_phrase, fold, tokens
from afandem.scenarios.schema import Column, ColumnText, Scenario

RULE = "follow_up_lexicon"
LEXICON_COLUMNS: tuple[Column, ...] = ("egy", "cs", "arabizi", "cs_latin")


def _found(toks: list[str], forms: list[tuple[str, Phrase]]) -> list[str]:
    return [shown for shown, form in forms if contains_phrase(toks, form)]


def _time_args_are_windows(scenario: Scenario) -> bool | None:
    """None when no expected call has a time argument; else whether all are lists of ≥ 2."""
    values = [
        value
        for call in scenario.expected.tool_calls
        for key, value in call.args.items()
        if key == "time" or key.endswith("_time")
    ]
    if not values:
        return None
    return all(isinstance(value, list) and len(value) >= 2 for value in values)


def _field_findings(scenario: Scenario, name: Column, field: str, text: str) -> list[Finding]:
    lex = lexicons.follow_up()
    toks = tokens(fold(text))
    yes = _found(toks, lexicons.phrases(lex.yes))
    findings: list[Finding] = []
    if name in LEXICON_COLUMNS and not yes:
        severity: Severity = "error" if field == "confirm_yes" else "warning"
        message = f"no yes word from the lexicon (e.g. {quote(lex.yes[:2])}, aywa, ok)"
        findings.append(Finding(RULE, message, column=name, field=field, severity=severity))
    khalas = _found(toks, lexicons.phrases(lex.ambiguous_alone))
    if khalas and not yes:
        message = f"{quote(khalas[:1])} is ambiguous and never stands without a yes word"
        findings.append(Finding(RULE, message, column=name, field=field))
    no = _found(toks, lexicons.phrases(lex.no))
    if field == "confirm_yes" and no:
        message = f"a 'yes, go ahead' text contains the no word(s) {', '.join(no)}"
        findings.append(Finding(RULE, message, column=name, field=field, severity="warning"))
    periods = _found(toks, lexicons.phrases(lex.period_words))
    if field == "follow_up" and periods and _time_args_are_windows(scenario) is False:
        message = (
            f"period word {', '.join(periods)} makes the gold a window: "
            "the expected time must be a list"
        )
        findings.append(Finding(RULE, message, column=name, field=field))
    return findings


def check_follow_up_lexicon(scenario: Scenario) -> list[Finding]:
    findings: list[Finding] = []
    for name, block in scenario.texts.columns():
        for field, text in _confirmations(block):
            findings.extend(_field_findings(scenario, name, field, text))
    return findings


def _confirmations(block: ColumnText) -> list[tuple[str, str]]:
    pairs = [("follow_up", block.follow_up), ("confirm_yes", block.confirm_yes)]
    return [(field, text) for field, text in pairs if text is not None]
