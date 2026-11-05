"""Pydantic models for one scenario file (docs/dataset-spec.md §1).

One scenario is one meaning, one checkable outcome and six texts. Everything that is not
text is shared, so paired runs differ only in the text. The models reject unknown keys
(`extra="forbid"`) and enforce the cross-field rules that decide whether a file is
well-formed; the softer authoring rules (dialect markers, Arabizi spelling, length ratio and
so on) live in `afandem.lints`, which reports findings instead of refusing the file.
"""

import datetime as dt
import re
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Final, Literal, Self, get_args
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

SCHEMA_VERSION: Final = "1.0"

Domain = Literal["clinic", "banking", "telecom"]
Behaviour = Literal["act", "inform", "ask", "none", "refuse", "out_of_scope"]
Column = Literal["en", "msa", "egy", "arabizi", "cs", "cs_latin"]
Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HarmType = Literal["explicit_mismatch", "inferable_mismatch"]
Gender = Literal["m", "f"]
Register = Literal["polite", "neutral", "terse", "angry"]
AuthoringBatch = Literal["pilot", "post_pilot"]
Provenance = Literal["hand", "assistant_draft"]
"""Who wrote a text. `hand`: typed by the native-speaker author (the only value the measured
set accepts). `assistant_draft`: drafted by the AI assistant at the author's request and not yet
rewritten or approved by her; valid for runs, an error in `afandem data lint` (decision D19)."""

CulturalTag = Literal[
    "date_relative_day",
    "date_relative_weekday",
    "date_numeric_dmy",
    "number_words_money",
    "negation_hedge_abort",
    "third_party_request",
    "date_month_part",
    "date_hijri_ramadan",
    "weekend_eg",
    "time_colloquial",
    "phone_eg",
    "name_two_part",
    "name_four_part",
    "name_ambiguous",
    "name_kunya_title",
    "specialty_eg",
    "visit_type",
    "earliest_slot",
    "multi_intent",
    "politeness_indirect",
    "addressee_feminine",
    "register_terse",
    "greeting_prefix",
    "hyperbole_alarming",
    "idiom_religious",
    "idiom_violent",
    "register_angry",
    "uncertainty_ask",
    "money_constraint",
]
OrthographicTag = Literal[
    "digits_arabic_indic",
    "digits_mixed",
    "letter_variants",
    "typo_keyboard",
    "typo_phonetic",
    "elongation_emoji",
    "arabizi_digit_letter",
    "arabizi_digit_clash",
    "loan_arabic_script",
    "cs_insertion",
]

DOMAINS: Final[tuple[Domain, ...]] = get_args(Domain)
BEHAVIOURS: Final[tuple[Behaviour, ...]] = get_args(Behaviour)
COLUMNS: Final[tuple[Column, ...]] = get_args(Column)
WEEKDAYS: Final[tuple[Weekday, ...]] = get_args(Weekday)  # index = date.weekday()
CULTURAL_TAGS: Final[tuple[CulturalTag, ...]] = get_args(CulturalTag)
ORTHOGRAPHIC_TAGS: Final[tuple[OrthographicTag, ...]] = get_args(OrthographicTag)
NOISE_TAGS: Final[frozenset[OrthographicTag]] = frozenset(
    {"letter_variants", "typo_keyboard", "typo_phonetic", "elongation_emoji"}
)

ARABIC_SCRIPT_COLUMNS: Final[tuple[Column, ...]] = ("msa", "egy", "cs")
LATIN_ARABIZI_COLUMNS: Final[tuple[Column, ...]] = ("arabizi", "cs_latin")
CS_COLUMNS: Final[tuple[Column, ...]] = ("cs", "cs_latin")

CAIRO_TZ_NAME: Final = "Africa/Cairo"
CAIRO: Final = ZoneInfo(CAIRO_TZ_NAME)

# Tool names per domain and whether each mutates state (docs/dataset-spec.md §4). The
# sandbox registry becomes the source of truth once it exists; this table only lets the
# schema reject unknown names and expected writes to read-only tools.
DOMAIN_TOOLS: Final[Mapping[Domain, Mapping[str, bool]]] = {
    "clinic": {
        "find_patient": False,
        "list_doctors": False,
        "search_slots": False,
        "get_appointments": False,
        "book_appointment": True,
        "reschedule_appointment": True,
        "cancel_appointment": True,
    },
    "telecom": {
        "get_account": False,
        "list_bundles": False,
        "list_services": False,
        "change_bundle": True,
        "recharge": True,
        "unsubscribe": True,
        "transfer_credit": True,
        "report_sim_lost": True,
    },
    "banking": {
        "get_balance": False,
        "list_transactions": False,
        "list_beneficiaries": False,
        "transfer": True,
        "block_card": True,
    },
}

ID_PATTERN: Final = r"^(clinic|banking|telecom)-[0-9]{4}$"
LOCAL_DATETIME_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([+-][0-9]{2}:[0-9]{2})?$"
)
_LOCAL_DATETIME_RE: Final = re.compile(LOCAL_DATETIME_PATTERN)

NonEmptyStr = Annotated[StrictStr, StringConstraints(min_length=1, pattern=r"\S")]
ScenarioId = Annotated[StrictStr, StringConstraints(pattern=ID_PATTERN)]
Revision = Annotated[StrictInt, Field(ge=1)]
Natural = Annotated[StrictInt, Field(ge=1, le=5)]
SlotScalar = StrictBool | StrictInt | StrictStr | None
SlotValue = SlotScalar | list[StrictBool | StrictInt | StrictStr]
LocalDateTime = Annotated[
    dt.datetime,
    WithJsonSchema(
        {
            "type": "string",
            "pattern": LOCAL_DATETIME_PATTERN,
            "description": "Africa/Cairo wall-clock time, ISO 8601 with seconds; an explicit "
            "UTC offset is optional and, when given, must be Cairo's offset at that instant.",
        }
    ),
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def cairo_datetime(local: dt.datetime) -> dt.datetime:
    """Return `local` as an aware Africa/Cairo datetime, DST-correct.

    A naive value is read as Cairo wall-clock time; it must exist (not inside the spring
    gap) and be unambiguous (not inside the autumn repeated hour). An aware value must carry
    the offset Cairo actually had at that wall-clock time.
    """
    naive = local.replace(tzinfo=None, fold=0)
    candidates: dict[dt.timedelta, dt.datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=CAIRO, fold=fold)
        round_trip = aware.astimezone(dt.UTC).astimezone(CAIRO)
        offset = aware.utcoffset()
        if offset is not None and round_trip.replace(tzinfo=None, fold=0) == naive:
            candidates.setdefault(offset, aware)
    if not candidates:
        raise ValueError(f"{naive.isoformat()} does not exist in {CAIRO_TZ_NAME} (DST gap)")
    given = local.utcoffset()
    if given is not None:
        if given not in candidates:
            expected = " or ".join(_format_offset(offset) for offset in candidates)
            raise ValueError(
                f"offset {_format_offset(given)} does not match {CAIRO_TZ_NAME} "
                f"({expected}) at {naive.isoformat()}"
            )
        return candidates[given]
    if len(candidates) > 1:
        raise ValueError(
            f"{naive.isoformat()} is ambiguous in {CAIRO_TZ_NAME} (DST repeated hour); "
            "write the offset explicitly"
        )
    return next(iter(candidates.values()))


def _format_offset(offset: dt.timedelta) -> str:
    minutes = int(offset.total_seconds()) // 60
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{mins:02d}"


class ChangelogEntry(_Model):
    revision: Revision
    date: dt.date
    note: NonEmptyStr


class Now(_Model):
    """The scenario clock: Cairo wall-clock time plus the weekday it falls on."""

    local: LocalDateTime
    tz: Literal["Africa/Cairo"]
    weekday: Weekday

    @field_validator("local", mode="before")
    @classmethod
    def _local_is_iso_text(cls, value: object) -> object:
        if isinstance(value, dt.datetime):
            return value
        if not isinstance(value, str) or not _LOCAL_DATETIME_RE.fullmatch(value):
            raise ValueError("expected YYYY-MM-DDTHH:MM:SS with an optional ±HH:MM offset")
        return value

    @model_validator(mode="after")
    def _check_zone_and_weekday(self) -> Self:
        aware = cairo_datetime(self.local)
        actual = WEEKDAYS[aware.weekday()]
        if actual != self.weekday:
            raise ValueError(f"weekday is {self.weekday} but {aware.date()} is a {actual}")
        return self

    @property
    def aware(self) -> dt.datetime:
        """The aware Africa/Cairo datetime."""
        return cairo_datetime(self.local)

    @property
    def local_date(self) -> dt.date:
        return self.local.date()


class ToolCall(_Model):
    name: NonEmptyStr
    args: dict[str, JsonValue] = Field(
        description="Normalised arguments; a list holds the acceptable values for that field."
    )


class AnswerForm(_Model):
    value: StrictStr | StrictInt = Field(description="The normalised value (digits match it).")
    forms: list[NonEmptyStr] = Field(description="Per-column surface forms of the value.")


class Expected(_Model):
    end_state_patch: dict[str, JsonValue] = Field(
        description="Changes to initial_state after a successful episode; {} = unchanged."
    )
    tool_calls: list[ToolCall] = Field(description="Expected validated writes.")
    must_not_call: list[NonEmptyStr] = Field(description="Tools (reads included) never to call.")
    read_calls: list[ToolCall] | None = Field(default=None, description="inform items only.")
    answer_must_contain: list[AnswerForm] | None = Field(
        default=None, description="inform items (required); act items may use it too."
    )
    expected_clarification: NonEmptyStr | None = Field(
        default=None, description="ask items: the slot the clarifying question must be about."
    )
    reply_language: Literal["user"]


class Insertion(_Model):
    text: NonEmptyStr
    tool_cue: StrictBool = Field(description="Does the insertion name or nearly name a tool?")


class ColumnText(_Model):
    """One of the six texts plus its per-column annotations."""

    text: NonEmptyStr
    follow_up: NonEmptyStr | None = Field(
        default=None, description="ask items: the answer to the clarification plus a confirmation."
    )
    confirm_yes: NonEmptyStr | None = Field(default=None, description="act items: 'yes, go ahead'.")
    phenomena: list[OrthographicTag]
    insertions: list[Insertion] | None = Field(
        default=None, description="cs and cs_latin only: the English content insertions."
    )
    arabizi_profile: Literal["house"] | None = Field(
        default=None, description="arabizi and cs_latin only."
    )
    phenomenon_realised: dict[CulturalTag, StrictBool]
    natural: Natural = Field(description="Self-rating 1-5; published, never a gate.")
    provenance: Provenance

    def fields_with_text(self) -> Iterator[tuple[str, str]]:
        """Yield (field name, text) for text, follow_up and confirm_yes when present."""
        yield "text", self.text
        if self.follow_up is not None:
            yield "follow_up", self.follow_up
        if self.confirm_yes is not None:
            yield "confirm_yes", self.confirm_yes


class ArabiziVariant(_Model):
    text: NonEmptyStr
    profile: Literal["variant"]
    provenance: Provenance


class Texts(_Model):
    en: ColumnText
    msa: ColumnText
    egy: ColumnText
    arabizi: ColumnText
    cs: ColumnText
    cs_latin: ColumnText

    def column(self, name: Column) -> ColumnText:
        block: ColumnText = getattr(self, name)
        return block

    def columns(self) -> Iterator[tuple[Column, ColumnText]]:
        """Yield the six columns in canonical order."""
        for name in COLUMNS:
            yield name, self.column(name)


class Scenario(_Model):
    """One scenario file, schema_version 1.0."""

    model_config = ConfigDict(
        title="Afandem scenario",
        json_schema_extra={
            "description": "One Afandem scenario (docs/dataset-spec.md §1). Cross-field rules "
            "(behaviour-specific fields, tool names, changelog) are enforced by the pydantic "
            "model in afandem.scenarios.schema and by `afandem data lint`."
        },
    )

    schema_version: Literal["1.0"]
    id: ScenarioId
    revision: Revision
    changelog: list[ChangelogEntry] = Field(min_length=1)
    authoring_batch: AuthoringBatch
    fixed_after_pilot: StrictBool
    domain: Domain
    behaviour: Behaviour
    now: Now
    user_identity: dict[str, NonEmptyStr] = Field(min_length=1)
    tools: list[NonEmptyStr] = Field(min_length=1)
    initial_state: dict[str, Any]
    slots: dict[str, SlotValue]
    expected: Expected
    control_of: ScenarioId | None = None
    harm_type: HarmType | None = None
    gender: Gender = Field(description="The speaker's gender, constant across the six texts.")
    # `register` would shadow ABCMeta.register on the model class; the JSON key is unchanged.
    register_: Register = Field(alias="register")
    phenomena: list[CulturalTag]
    texts: Texts
    arabizi_variant: ArabiziVariant | None = None
    canary: NonEmptyStr

    @model_validator(mode="after")
    def _cross_field_rules(self) -> Self:
        problems = [
            *_identity_problems(self),
            *_behaviour_problems(self),
            *_column_problems(self),
            *_tool_problems(self),
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def tool_mutates(self, name: str) -> bool | None:
        """True/False for a known tool of this domain, None for an unknown name."""
        return DOMAIN_TOOLS[self.domain].get(name)


def _identity_problems(s: Scenario) -> Iterator[str]:
    if s.id.split("-", 1)[0] != s.domain:
        yield f"id: {s.id!r} must start with the domain {s.domain!r}"
    revisions = [entry.revision for entry in s.changelog]
    if revisions != list(range(1, s.revision + 1)):
        yield f"changelog: revisions {revisions} must run 1..{s.revision} (the current revision)"
    dates = [entry.date for entry in s.changelog]
    if dates != sorted(dates):
        yield "changelog: dates must not go backwards"
    if s.fixed_after_pilot and s.authoring_batch != "pilot":
        yield "fixed_after_pilot: only pilot items can be fixed after the pilot"
    if s.control_of is not None:
        if s.control_of == s.id:
            yield "control_of: a scenario cannot be its own control twin"
        if s.behaviour not in ("act", "inform"):
            yield "control_of: only act or inform controls point to a refuse twin"
    if not isinstance(s.slots.get("intent"), str) or not s.slots["intent"]:
        yield "slots.intent: required (a non-empty string)"
    if len(set(s.phenomena)) != len(s.phenomena):
        yield "phenomena: duplicate tags"


def _behaviour_problems(s: Scenario) -> Iterator[str]:
    if (s.behaviour == "refuse") != (s.harm_type is not None):
        yield "harm_type: required for refuse items and only for them"
    yield from _clarification_problems(s)
    yield from _inform_problems(s)
    yield from _write_problems(s)


def _clarification_problems(s: Scenario) -> Iterator[str]:
    wanted = s.expected.expected_clarification
    if s.behaviour != "ask":
        if wanted is not None:
            yield "expected.expected_clarification: only ask items have one"
    elif wanted is None:
        yield "expected.expected_clarification: required for ask items"
    elif wanted not in s.slots:
        yield f"expected.expected_clarification: {wanted!r} is not a key of slots"


def _inform_problems(s: Scenario) -> Iterator[str]:
    exp = s.expected
    if s.behaviour == "inform":
        if not exp.read_calls:
            yield "expected.read_calls: required (non-empty) for inform items"
        if not exp.answer_must_contain:
            yield "expected.answer_must_contain: required (non-empty) for inform items"
        return
    if exp.read_calls is not None:
        yield "expected.read_calls: only inform items have read calls"
    if exp.answer_must_contain is not None and s.behaviour != "act":
        yield "expected.answer_must_contain: only inform (and act) items have one"


def _write_problems(s: Scenario) -> Iterator[str]:
    exp = s.expected
    if s.behaviour in ("act", "ask"):
        if not exp.tool_calls:
            yield f"expected.tool_calls: {s.behaviour} items expect at least one write"
        return
    if exp.tool_calls:
        yield f"expected.tool_calls: {s.behaviour} items expect no write"
    if exp.end_state_patch:
        yield f"expected.end_state_patch: {s.behaviour} items leave the state unchanged ({{}})"


def _column_problems(s: Scenario) -> Iterator[str]:
    for name, block in s.texts.columns():
        where = f"texts.{name}"
        if s.behaviour == "ask" and block.follow_up is None:
            yield f"{where}.follow_up: required for ask items"
        if s.behaviour != "ask" and block.follow_up is not None:
            yield f"{where}.follow_up: only ask items have a follow-up"
        if s.behaviour == "act" and block.confirm_yes is None:
            yield f"{where}.confirm_yes: required for act items"
        if s.behaviour != "act" and block.confirm_yes is not None:
            yield f"{where}.confirm_yes: only act items have a confirmation"
        if name in CS_COLUMNS and block.insertions is None:
            yield f"{where}.insertions: required on code-switched columns"
        if name not in CS_COLUMNS and block.insertions is not None:
            yield f"{where}.insertions: only cs and cs_latin carry insertions"
        if name not in LATIN_ARABIZI_COLUMNS and block.arabizi_profile is not None:
            yield f"{where}.arabizi_profile: only arabizi and cs_latin have a profile"
        if len(set(block.phenomena)) != len(block.phenomena):
            yield f"{where}.phenomena: duplicate tags"


def _tool_problems(s: Scenario) -> Iterator[str]:
    known = DOMAIN_TOOLS[s.domain]
    if len(set(s.tools)) != len(s.tools):
        yield "tools: duplicate names"
    unknown = [name for name in s.tools if name not in known]
    if unknown:
        yield f"tools: {unknown} are not {s.domain} tools"
    offered = set(s.tools)
    exp = s.expected
    for call in exp.tool_calls:
        if call.name not in offered:
            yield f"expected.tool_calls: {call.name!r} is not in tools"
        elif not known.get(call.name, False):
            yield f"expected.tool_calls: {call.name!r} does not mutate state (use read_calls)"
    for call in exp.read_calls or []:
        if call.name not in offered:
            yield f"expected.read_calls: {call.name!r} is not in tools"
        elif known.get(call.name, False):
            yield f"expected.read_calls: {call.name!r} mutates state"
    for name in exp.must_not_call:
        if name not in offered:
            yield f"expected.must_not_call: {name!r} is not in tools"
    clash = sorted({call.name for call in exp.tool_calls} & set(exp.must_not_call))
    if clash:
        yield f"expected: {clash} are both expected and in must_not_call"
