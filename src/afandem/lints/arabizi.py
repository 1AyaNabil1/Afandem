"""Arabizi house profile (docs/dataset-spec.md §2, Arabizi; lint table).

"Written as pronounced" cannot be linted. What can: in the house profile (arabizi, cs_latin)
no `6`/`9`/`8` used as letters, no `kh`, no `3'`, no `q` outside /q/-words, article `el`
rather than the variant `al`/`l`/`ll`, and none of the spec's qaf-deletion forms (`aal`,
`alb`). Names from the scenario state (aliases, passport romanisation) and declared CS
insertions are exempt, as are number tokens such as `8k`, `8pm`, `8th`. The
`arabizi_variant` text must differ from the house text in at least two of these features.
"""

import re
import unicodedata
from collections.abc import Iterable

from afandem.lints import lexicons
from afandem.lints.context import latin_name_tokens
from afandem.lints.findings import Finding, Severity
from afandem.lints.text import phrase
from afandem.scenarios.schema import Scenario

RULE = "arabizi_profile"
_APOSTROPHES = "'\N{RIGHT SINGLE QUOTATION MARK}"
_WORD = re.compile(f"[a-z0-9{_APOSTROPHES}]+")
_NUMBER_TOKEN = re.compile(r"^[0-9]+(?:k|am|pm|st|nd|rd|th)?$")

FEATURE_LABELS = {
    "digit_6": "6 as a letter",
    "digit_9": "9 as a letter",
    "digit_8": "8 as a letter",
    "kh": "kh (house: 5)",
    "3'": "3' (house: gh)",
    "q": "q outside /q/-words (house: 2)",
    "article": "al/l/ll article (house: el)",
    "q_deletion": "qaf-deletion form (house: 2)",
}


def arabizi_features(text: str, exempt: Iterable[str] = ()) -> dict[str, list[str]]:
    """Variant-profile features in an Arabizi text: feature → offending words."""
    lex = lexicons.arabizi()
    skip = set(exempt)
    q_words = [w.casefold() for w in lex.q_words]
    found: dict[str, list[str]] = {}
    for word in _WORD.findall(unicodedata.normalize("NFKC", text).casefold()):
        bare = word.strip(_APOSTROPHES)
        if not bare or bare in skip or _NUMBER_TOKEN.match(bare):
            continue
        for digit in lex.digit_letters:
            if re.search(f"[a-z]{digit}|{digit}[a-z]", bare):
                found.setdefault(f"digit_{digit}", []).append(bare)
        for sequence in lex.forbidden_sequences:
            normalised = word.replace(_APOSTROPHES[1], "'")
            if sequence in normalised:
                found.setdefault(sequence, []).append(bare)
        if "q" in bare and not any(bare.startswith(q) for q in q_words):
            found.setdefault("q", []).append(bare)
        if bare in lex.variant_articles:
            found.setdefault("article", []).append(bare)
        if bare in lex.variant_words:
            found.setdefault("q_deletion", []).append(bare)
    return found


def _exempt(scenario: Scenario) -> set[str]:
    names = set(latin_name_tokens(scenario.initial_state))
    for block in (scenario.texts.cs_latin,):
        for item in block.insertions or []:
            names.update(phrase(item.text))
    return names


def check_arabizi_profile(scenario: Scenario) -> list[Finding]:
    exempt = _exempt(scenario)
    findings: list[Finding] = []
    for name in ("arabizi", "cs_latin"):
        for field, text in scenario.texts.column(name).fields_with_text():
            for feature, words in arabizi_features(text, exempt).items():
                message = (
                    f"house profile: {FEATURE_LABELS.get(feature, feature)} in "
                    f"{', '.join(repr(w) for w in words)}"
                )
                findings.append(Finding(RULE, message, column=name, field=field))
    variant = scenario.arabizi_variant
    if variant is None:
        return findings
    house_text = scenario.texts.arabizi.text
    if phrase(variant.text) == phrase(house_text):
        message = "the variant text is the house text"
        findings.append(Finding(RULE, message, column="arabizi_variant", field="text"))
        return findings
    added = sorted(
        set(arabizi_features(variant.text, exempt)) - set(arabizi_features(house_text, exempt))
    )
    minimum = lexicons.arabizi().min_variant_features
    if len(added) < minimum:
        labels = ", ".join(FEATURE_LABELS.get(f, f) for f in added) or "none"
        message = (
            f"the variant differs from the house text in {len(added)} detectable profile "
            f"feature(s) ({labels}); it needs ≥ {minimum} (dropped vowels and digits for "
            "amounts are not detectable: check by hand)"
        )
        severity: Severity = "error" if not added else "manual"
        findings.append(
            Finding(RULE, message, column="arabizi_variant", field="text", severity=severity)
        )
    return findings
