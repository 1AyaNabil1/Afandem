"""Variety lints for the Arabic-script columns (docs/dataset-spec.md §2, lint table).

- `egyptian_marker`: EGY and CS texts carry at least one Egyptian marker.
- `msa_ism`: no whole-word, clitic-aware MSA-ism in EGY or CS (text, follow-up, confirm).
- `msa_egyptian_syntax`: no Egyptian marker, no "bitaa", no verb-first future ha-, and none
  of the spec's four banned particles in MSA.
- `diacritics`: none in EGY, CS or MSA.
- `gender`: a heuristic on the speaker's "want" participle (warnings; the spec defines no
  mechanical gender check).

Word lists and their sources are in `lexicons/egyptian.json`, `msa.json` and `gender.json`.
"""

from collections.abc import Iterator

from afandem.lints import lexicons
from afandem.lints.findings import Finding
from afandem.lints.text import (
    CONJUNCTIONS,
    contains_phrase,
    fold,
    is_arabic,
    light_fold,
    phrase,
    tokens,
    words_with_diacritics,
)
from afandem.scenarios.schema import Column, Scenario

SHADDA = "\N{ARABIC SHADDA}"
FUTURE_HA = "\N{ARABIC LETTER HEH}"
FUTURE_PERSON_LETTERS = frozenset(
    "\N{ARABIC LETTER TEH}\N{ARABIC LETTER YEH}\N{ARABIC LETTER NOON}"
)
FUTURE_MIN_LENGTH = 5


def _fields(scenario: Scenario, columns: tuple[Column, ...]) -> Iterator[tuple[str, str, str]]:
    for name in columns:
        for field, text in scenario.texts.column(name).fields_with_text():
            yield name, field, text


def quote(forms: list[str]) -> str:
    return ", ".join(
        f"\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}{form}"
        f"\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}"
        for form in forms
    )


def _without_conjunction(token: str) -> list[str]:
    if token[:1] in CONJUNCTIONS and len(token) > 1:
        return [token, token[1:]]
    return [token]


def egyptian_markers(text: str) -> tuple[list[str], list[str]]:
    """(lexicon markers found, heuristic ha-/bi- + imperfect verb words found)."""
    lex = lexicons.egyptian()
    toks = tokens(fold(text))
    strong = [shown for shown, form in lexicons.phrases(lex.markers) if contains_phrase(toks, form)]
    prefixes = [phrase(word)[0] for word in lex.prefix_markers]
    strong.extend(
        token
        for token in toks
        if any(
            variant.startswith(prefix) and variant != prefix
            for variant in _without_conjunction(token)
            for prefix in prefixes
        )
    )
    verb_prefixes = {fold(prefix) for prefix in lex.verb_prefixes}
    letters = {fold(letter) for letter in lex.imperfect_letters}
    weak = [
        token
        for token in toks
        if is_arabic(token)
        and len(token) >= lex.verb_min_length
        and token[0] in verb_prefixes
        and token[1] in letters
    ]
    return strong, weak


def check_egyptian_markers(scenario: Scenario) -> list[Finding]:
    rule = "egyptian_marker"
    examples = quote(lexicons.egyptian().markers[:3])
    findings: list[Finding] = []
    for name in ("egy", "cs"):
        strong, weak = egyptian_markers(scenario.texts.column(name).text)
        if strong:
            continue
        if weak:
            message = (
                f"only the heuristic ha-/bi- + verb marker matched ({quote(weak)}); "
                "confirm the text is Egyptian"
            )
            findings.append(Finding(rule, message, column=name, field="text", severity="warning"))
        else:
            message = f"no Egyptian marker (at least one from the spec list, e.g. {examples})"
            findings.append(Finding(rule, message, column=name, field="text"))
    return findings


def msa_isms(text: str) -> list[str]:
    """MSA-isms in a text: whole word, clitic-aware, after folding."""
    lex = lexicons.msa()
    exact = {phrase(word) for word in lex.exact_only}
    toks = tokens(fold(text))
    return [
        shown
        for shown, form in lexicons.phrases(lex.msa_isms)
        if contains_phrase(toks, form, proclitics=form not in exact)
    ]


def check_msa_isms(scenario: Scenario) -> list[Finding]:
    findings: list[Finding] = []
    for name, field, text in _fields(scenario, ("egy", "cs")):
        found = msa_isms(text)
        if found:
            message = f"MSA-ism {quote(found)} in an Egyptian text"
            findings.append(Finding("msa_ism", message, column=name, field=field))
    return findings


def future_ha(text: str) -> tuple[list[str], list[str]]:
    """Verb-first future ha-: (written with hamza, certain; ha- + t/y/n, possible)."""
    hamza = lexicons.msa().future_with_hamza
    certain = [t for t in tokens(light_fold(text)) if t.startswith(hamza) and len(t) > len(hamza)]
    possible = [
        t
        for t in tokens(fold(text))
        if len(t) >= FUTURE_MIN_LENGTH and t[0] == FUTURE_HA and t[1] in FUTURE_PERSON_LETTERS
    ]
    return certain, possible


def inna(text: str) -> tuple[bool, bool]:
    """(the particle written with shadda present, the bare spelling present)."""
    target = tokens(light_fold(lexicons.msa().inna))
    with_shadda = bare = False
    for word in text.split():
        if tokens(light_fold(word)) == target:
            if SHADDA in word:
                with_shadda = True
            else:
                bare = True
    return with_shadda, bare


def msa_syntax_problems(text: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one MSA text."""
    lex_egy, lex_msa = lexicons.egyptian(), lexicons.msa()
    errors: list[str] = []
    warnings: list[str] = []
    strong, _ = egyptian_markers(text)
    soft = {phrase(word) for word in lex_egy.msa_warning_only}
    hard = [marker for marker in strong if phrase(marker) not in soft]
    if hard:
        errors.append(f"Egyptian marker {quote(hard)}")
    shared = [marker for marker in strong if phrase(marker) in soft]
    if shared:
        warnings.append(f"{quote(shared)} is Egyptian ('there is') or MSA ('in it'): check")
    toks = tokens(fold(text))
    banned = [
        w for w, form in lexicons.phrases(lex_msa.msa_forbidden) if contains_phrase(toks, form)
    ]
    if banned:
        errors.append(f"{quote(banned)} is banned in MSA")
    certain, possible = future_ha(text)
    if certain:
        errors.append(f"verb-first future ha- {quote(certain)}")
    if possible:
        warnings.append(f"possible verb-first future ha- {quote(possible)}")
    with_shadda, bare = inna(text)
    if with_shadda:
        errors.append(f"{quote([lex_msa.inna])} is banned in MSA")
    if bare:
        warnings.append(f"{quote([lex_msa.inna])} without shadda, or the conditional (fine): check")
    return errors, warnings


def check_msa_syntax(scenario: Scenario) -> list[Finding]:
    rule = "msa_egyptian_syntax"
    findings: list[Finding] = []
    for name, field, text in _fields(scenario, ("msa",)):
        errors, warnings = msa_syntax_problems(text)
        findings.extend(Finding(rule, message, column=name, field=field) for message in errors)
        findings.extend(
            Finding(rule, message, column=name, field=field, severity="warning")
            for message in warnings
        )
    return findings


def check_diacritics(scenario: Scenario) -> list[Finding]:
    findings: list[Finding] = []
    for name, field, text in _fields(scenario, ("egy", "cs", "msa")):
        words = words_with_diacritics(text)
        if words:
            message = f"diacritics in {quote(words)}"
            findings.append(Finding("diacritics", message, column=name, field=field))
    return findings


def check_gender(scenario: Scenario) -> list[Finding]:
    lex = lexicons.gender()
    other = lex.masculine if scenario.gender == "f" else lex.feminine
    label = "masculine" if scenario.gender == "f" else "feminine"
    forms = lexicons.phrases(other, light=True)
    texts = list(_fields(scenario, ("msa", "egy", "arabizi", "cs", "cs_latin")))
    if scenario.arabizi_variant is not None:
        texts.append(("arabizi_variant", "text", scenario.arabizi_variant.text))
    findings: list[Finding] = []
    for name, field, text in texts:
        toks = tokens(light_fold(text))
        found = [shown for shown, form in forms if contains_phrase(toks, form)]
        if found:
            message = (
                f"speaker gender is {scenario.gender!r} but {quote(found)} is {label}; "
                "check it refers to someone else"
            )
            findings.append(
                Finding("gender", message, column=name, field=field, severity="warning")
            )
    return findings
