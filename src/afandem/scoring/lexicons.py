"""Typed access to the scoring word lists in `lexicons/*.json`.

Each file carries `source` and `notes` saying where its entries come from and which judgement
calls they encode (docs/decisions.md D22, proposed). They are linguistic resources, never
benchmark text. Number words are shared with the lints (`afandem.lints.lexicons.numbers`).
"""

from functools import cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Script = Literal["arabic", "arabizi", "english"]


class _Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    notes: list[str] = Field(default_factory=list)


class _ByScript(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arabic: list[str] = Field(default_factory=list)
    arabizi: list[str] = Field(default_factory=list)
    english: list[str] = Field(default_factory=list)

    def all(self) -> list[str]:
        return [*self.arabic, *self.arabizi, *self.english]


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forms: list[str]
    shift: Literal["am", "noon", "pm"]
    window: tuple[str, str]


class TimeLexicon(_Lexicon):
    hours: dict[int, list[str]]
    minutes_after: dict[str, int]
    minutes_before: dict[str, int]
    periods: list[Period]
    single_letter_periods: dict[str, Literal["am", "pm"]]
    markers: list[str]
    oclock: list[str]


class MoneyLexicon(_Lexicon):
    currency: list[str]
    half: list[str]
    thousands_suffix: list[str]


class ClaimsDoneLexicon(_Lexicon):
    markers: _ByScript
    guards: _ByScript
    guard_window: int = Field(ge=0)
    not_claims: _ByScript
    question_starters: list[str]


class ClassifierLexicon(_Lexicon):
    ask_markers: _ByScript
    confirm_markers: _ByScript
    alternative_markers: _ByScript
    refusal_markers: _ByScript
    acknowledge_markers: _ByScript
    courtesy_markers: _ByScript
    courtesy_purpose_guards: _ByScript
    courtesy_purpose_window: int = Field(ge=1)
    acknowledge_max_tokens: int = Field(ge=1)
    acknowledge_lead_tokens: int = Field(ge=1)
    slot_keywords: dict[str, list[str]]
    slot_categories: list[tuple[str, str]]


class ReplyLanguageLexicon(_Lexicon):
    arabizi_words: list[str]
    min_word_hits: int = Field(ge=1)
    unit_suffixes: list[str]


def _read(name: str) -> str:
    return (files("afandem.scoring") / "lexicons" / f"{name}.json").read_text(encoding="utf-8")


@cache
def time_words() -> TimeLexicon:
    return TimeLexicon.model_validate_json(_read("time"))


@cache
def money() -> MoneyLexicon:
    return MoneyLexicon.model_validate_json(_read("money"))


@cache
def claims_done() -> ClaimsDoneLexicon:
    return ClaimsDoneLexicon.model_validate_json(_read("claims_done"))


@cache
def classifier() -> ClassifierLexicon:
    return ClassifierLexicon.model_validate_json(_read("classifier"))


@cache
def reply_language() -> ReplyLanguageLexicon:
    return ReplyLanguageLexicon.model_validate_json(_read("reply_language"))


__all__ = [
    "ClaimsDoneLexicon",
    "ClassifierLexicon",
    "MoneyLexicon",
    "Period",
    "ReplyLanguageLexicon",
    "Script",
    "TimeLexicon",
    "claims_done",
    "classifier",
    "money",
    "reply_language",
    "time_words",
]
