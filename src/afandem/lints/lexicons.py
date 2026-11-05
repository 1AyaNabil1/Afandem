"""Typed access to the word lists in `lexicons/*.json` (copied from docs/dataset-spec.md).

The JSON files are the place to extend a list; each carries `source` and `notes` saying
where its entries come from.
"""

from functools import cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field

from afandem.lints.text import Phrase, phrase
from afandem.scenarios.schema import Weekday


class _Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    notes: list[str] = Field(default_factory=list)


class EgyptianLexicon(_Lexicon):
    markers: list[str]
    prefix_markers: list[str]
    verb_prefixes: list[str]
    imperfect_letters: list[str]
    verb_min_length: int
    msa_warning_only: list[str]


class MsaLexicon(_Lexicon):
    msa_isms: list[str]
    exact_only: list[str]
    msa_forbidden: list[str]
    inna: str
    future_with_hamza: str


class WeekdayForms(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arabic: list[str]
    arabizi: list[str]
    english: list[str]


class DatesLexicon(_Lexicon):
    weekdays: dict[Weekday, WeekdayForms]
    arabizi_articles: list[str]
    relative_days: dict[int, list[str]]
    relative_day_blockers: list[str]
    day_words: list[str]
    month_words: list[str]
    months: dict[int, list[str]]


class FollowUpLexicon(_Lexicon):
    yes: list[str]
    no: list[str]
    ambiguous_alone: list[str]
    period_words: list[str]


class CodeSwitchLexicon(_Lexicon):
    min_vocabulary: list[str]
    discourse_markers: list[str]
    tool_cue_words: list[str]
    article_forms: list[str]
    min_insertions: int
    max_insertions: int


class ArabiziLexicon(_Lexicon):
    digit_letters: list[str]
    forbidden_sequences: list[str]
    q_words: list[str]
    variant_articles: list[str]
    variant_words: list[str]
    min_variant_features: int


class NumbersLexicon(_Lexicon):
    forms: dict[str, int]


class GenderLexicon(_Lexicon):
    masculine: list[str]
    feminine: list[str]


class TopicTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: list[str]
    warning: list[str]


class HarmfulLexicon(_Lexicon):
    topics: dict[str, TopicTerms]
    exempt: list[str]
    step_words: list[str]
    sentence_min_words: int = Field(ge=1)
    max_refuse_sentences: int = Field(ge=1)


def _read(name: str) -> str:
    return (files("afandem.lints") / "lexicons" / f"{name}.json").read_text(encoding="utf-8")


@cache
def egyptian() -> EgyptianLexicon:
    return EgyptianLexicon.model_validate_json(_read("egyptian"))


@cache
def msa() -> MsaLexicon:
    return MsaLexicon.model_validate_json(_read("msa"))


@cache
def dates() -> DatesLexicon:
    return DatesLexicon.model_validate_json(_read("dates"))


@cache
def follow_up() -> FollowUpLexicon:
    return FollowUpLexicon.model_validate_json(_read("followup"))


@cache
def code_switch() -> CodeSwitchLexicon:
    return CodeSwitchLexicon.model_validate_json(_read("codeswitch"))


@cache
def arabizi() -> ArabiziLexicon:
    return ArabiziLexicon.model_validate_json(_read("arabizi"))


@cache
def numbers() -> NumbersLexicon:
    return NumbersLexicon.model_validate_json(_read("numbers"))


@cache
def gender() -> GenderLexicon:
    return GenderLexicon.model_validate_json(_read("gender"))


@cache
def harmful() -> HarmfulLexicon:
    return HarmfulLexicon.model_validate_json(_read("harmful"))


def phrases(forms: list[str], *, light: bool = False) -> list[tuple[str, Phrase]]:
    """(display form, folded phrase) pairs, de-duplicated on the folded phrase."""
    seen: set[Phrase] = set()
    result: list[tuple[str, Phrase]] = []
    for form in forms:
        folded = phrase(form, light=light)
        if folded and folded not in seen:
            seen.add(folded)
            result.append((form, folded))
    return result
