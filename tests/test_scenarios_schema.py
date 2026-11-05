"""Scenario schema: the spec's §1 example, the clock, and each cross-field rule.

Texts are the spec example (quoted, see tests/fixtures/scenarios) or `<column ...>`
placeholders; no scenario wording is written here.
"""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from afandem.scenarios import COLUMNS, DOMAIN_TOOLS, Scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"

Doc = dict[str, Any]


def example() -> Doc:
    data: Doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def as_ask(doc: Doc) -> Doc:
    doc["behaviour"] = "ask"
    doc["expected"]["expected_clarification"] = "new_time"
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
        doc["texts"][name]["follow_up"] = f"<{name} follow_up>"
    return doc


def _no_write(doc: Doc, behaviour: str) -> Doc:
    doc["behaviour"] = behaviour
    doc["expected"]["tool_calls"] = []
    doc["expected"]["end_state_patch"] = {}
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
    return doc


def as_inform(doc: Doc) -> Doc:
    _no_write(doc, "inform")
    doc["expected"]["read_calls"] = [{"name": "get_appointments", "args": {"patient_id": "p_17"}}]
    doc["expected"]["answer_must_contain"] = [{"value": "2026-11-05", "forms": ["<form>"]}]
    return doc


def as_none(doc: Doc) -> Doc:
    return _no_write(doc, "none")


def as_refuse(doc: Doc) -> Doc:
    _no_write(doc, "refuse")
    doc["harm_type"] = "explicit_mismatch"
    return doc


def as_banking(doc: Doc) -> Doc:
    doc["id"] = "banking-0001"
    doc["domain"] = "banking"
    doc["tools"] = list(DOMAIN_TOOLS["banking"])
    doc["initial_state"] = {"accounts": [{"id": "acc_1"}]}
    doc["slots"] = {"intent": "transfer", "amount_egp": 1250}
    doc["expected"] = {
        "end_state_patch": {"accounts[acc_1].balance_piastres": 0},
        "tool_calls": [
            {"name": "transfer", "args": {"from_account_id": "acc_1", "amount_egp": 1250}}
        ],
        "must_not_call": ["block_card"],
        "reply_language": "user",
    }
    return doc


def invalid(doc: Doc) -> str:
    with pytest.raises(ValidationError) as caught:
        Scenario.model_validate(doc)
    return str(caught.value)


def test_spec_example_validates() -> None:
    scenario = Scenario.model_validate(example())
    assert scenario.id == "clinic-0042"
    assert scenario.behaviour == "act"
    assert scenario.register_ == "polite"
    assert scenario.now.aware.isoformat() == "2026-11-04T10:00:00+02:00"
    assert scenario.texts.egy.natural == 5
    assert [name for name, _ in scenario.texts.columns()] == list(COLUMNS)
    assert scenario.tool_mutates("reschedule_appointment") is True
    assert scenario.tool_mutates("find_patient") is False
    assert scenario.tool_mutates("transfer") is None


def test_register_keeps_its_json_key() -> None:
    dumped = Scenario.model_validate(example()).model_dump(mode="json", by_alias=True)
    assert dumped["register"] == "polite"
    assert "register_" not in dumped


@pytest.mark.parametrize("convert", [as_ask, as_inform, as_none, as_refuse, as_banking])
def test_each_behaviour_and_domain_has_a_valid_shape(convert: Callable[[Doc], Doc]) -> None:
    Scenario.model_validate(convert(example()))


def test_out_of_scope_and_telecom_are_accepted() -> None:
    doc = _no_write(example(), "out_of_scope")
    doc["id"], doc["domain"] = "telecom-0003", "telecom"
    doc["tools"] = list(DOMAIN_TOOLS["telecom"])
    doc["expected"]["must_not_call"] = ["recharge"]
    assert Scenario.model_validate(doc).domain == "telecom"


# --- now ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "weekday", "offset"),
    [
        ("2026-11-04T10:00:00", "Wednesday", "+02:00"),
        ("2026-11-04T10:00:00+02:00", "Wednesday", "+02:00"),
        ("2026-07-01T10:00:00", "Wednesday", "+03:00"),
        ("2026-07-01T10:00:00+03:00", "Wednesday", "+03:00"),
        ("2026-10-29T23:30:00+03:00", "Thursday", "+03:00"),
        ("2026-10-29T23:30:00+02:00", "Thursday", "+02:00"),
    ],
)
def test_now_offset_is_cairo_and_dst_correct(local: str, weekday: str, offset: str) -> None:
    doc = example()
    doc["now"] = {"local": local, "tz": "Africa/Cairo", "weekday": weekday}
    aware = Scenario.model_validate(doc).now.aware
    assert aware.isoformat().endswith(offset)


@pytest.mark.parametrize(
    ("now", "message"),
    [
        ({"local": "2026-11-04T10:00:00", "weekday": "Thursday"}, "is a Wednesday"),
        ({"local": "2026-11-04T10:00:00+03:00", "weekday": "Wednesday"}, "does not match"),
        ({"local": "2026-07-01T10:00:00+02:00", "weekday": "Wednesday"}, "does not match"),
        ({"local": "2026-04-24T00:30:00", "weekday": "Friday"}, "DST gap"),
        ({"local": "2026-10-29T23:30:00", "weekday": "Thursday"}, "ambiguous"),
        ({"local": "2026-11-04 10:00", "weekday": "Wednesday"}, "YYYY-MM-DDTHH:MM:SS"),
        ({"local": "2026-11-04T10:00:00Z", "weekday": "Wednesday"}, "YYYY-MM-DDTHH:MM:SS"),
        ({"local": 1793779200, "weekday": "Wednesday"}, "YYYY-MM-DDTHH:MM:SS"),
    ],
)
def test_now_rejects(now: dict[str, Any], message: str) -> None:
    doc = example()
    doc["now"] = {"tz": "Africa/Cairo", **now}
    assert message in invalid(doc)


def test_now_timezone_must_be_cairo() -> None:
    doc = example()
    doc["now"]["tz"] = "Africa/Tripoli"
    assert "now.tz" in invalid(doc)


# --- strictness -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [(), ("texts", "egy"), ("expected",), ("now",), ("texts", "cs", "insertions", 0)],
)
def test_unknown_keys_are_rejected(path: tuple[str | int, ...]) -> None:
    doc = example()
    target: Any = doc
    for key in path:
        target = target[key]
    target["surprise"] = 1
    assert "Extra inputs are not permitted" in invalid(doc)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["texts"]["egy"].update(natural=6), "texts.egy.natural"),
        (lambda d: d["texts"]["egy"].update(natural="5"), "texts.egy.natural"),
        (lambda d: d.update(revision=True), "revision"),
        (lambda d: d.update(fixed_after_pilot="true"), "fixed_after_pilot"),
        (lambda d: d.update(register="rude"), "register"),
        (lambda d: d.update(schema_version="2.0"), "schema_version"),
        (lambda d: d.update(domain="travel"), "domain"),
        (lambda d: d.update(id="clinic-42"), "id"),
        (lambda d: d["texts"]["en"].update(text="   "), "texts.en.text"),
        (lambda d: d["texts"]["egy"]["phenomena"].append("emoji"), "texts.egy.phenomena"),
        (lambda d: d["phenomena"].append("sarcasm"), "phenomena"),
        (lambda d: d["texts"].pop("cs_latin"), "texts.cs_latin"),
        (lambda d: d["texts"]["msa"].update(provenance="llm"), "texts.msa.provenance"),
        (lambda d: d["arabizi_variant"].update(provenance="template"), "provenance"),
        (lambda d: d["arabizi_variant"].update(profile="house"), "arabizi_variant.profile"),
        (lambda d: d["texts"]["cs"]["insertions"][0].pop("tool_cue"), "tool_cue"),
        (lambda d: d.update(gender="x"), "gender"),
    ],
)
def test_field_types_are_strict(mutate: Callable[[Doc], object], message: str) -> None:
    doc = example()
    mutate(doc)
    assert message in invalid(doc)


# --- cross-field rules ----------------------------------------------------------------


def _drop_follow_up(doc: Doc) -> None:
    doc["texts"]["egy"]["follow_up"] = None


def _drop_confirm(doc: Doc) -> None:
    doc["texts"]["arabizi"]["confirm_yes"] = None


CROSS_FIELD: list[tuple[str, Callable[[Doc], Doc], Callable[[Doc], object], str]] = [
    (
        "ask needs follow_up in every column",
        as_ask,
        _drop_follow_up,
        "texts.egy.follow_up: required for ask items",
    ),
    (
        "inform has no follow_up",
        as_inform,
        lambda d: d["texts"]["en"].update(follow_up="<en follow_up>"),
        "texts.en.follow_up: only ask items have a follow-up",
    ),
    (
        "none has no follow_up",
        as_none,
        lambda d: d["texts"]["msa"].update(follow_up="<msa follow_up>"),
        "only ask items have a follow-up",
    ),
    (
        "refuse has no follow_up",
        as_refuse,
        lambda d: d["texts"]["cs"].update(follow_up="<cs follow_up>"),
        "only ask items have a follow-up",
    ),
    (
        "act has no follow_up",
        lambda d: d,
        lambda d: d["texts"]["cs"].update(follow_up="<cs follow_up>"),
        "only ask items have a follow-up",
    ),
    (
        "act needs confirm_yes",
        lambda d: d,
        _drop_confirm,
        "texts.arabizi.confirm_yes: required for act items",
    ),
    (
        "ask has no confirm_yes",
        as_ask,
        lambda d: d["texts"]["egy"].update(confirm_yes="<egy confirm>"),
        "texts.egy.confirm_yes: only act items have a confirmation",
    ),
    (
        "ask needs expected_clarification",
        as_ask,
        lambda d: d["expected"].update(expected_clarification=None),
        "expected.expected_clarification: required for ask items",
    ),
    (
        "expected_clarification names a slot",
        as_ask,
        lambda d: d["expected"].update(expected_clarification="colour"),
        "'colour' is not a key of slots",
    ),
    (
        "only ask has expected_clarification",
        lambda d: d,
        lambda d: d["expected"].update(expected_clarification="new_time"),
        "only ask items have one",
    ),
    ("refuse needs harm_type", as_refuse, lambda d: d.update(harm_type=None), "harm_type"),
    (
        "harm_type only on refuse",
        lambda d: d,
        lambda d: d.update(harm_type="inferable_mismatch"),
        "harm_type",
    ),
    (
        "inform needs answer_must_contain",
        as_inform,
        lambda d: d["expected"].update(answer_must_contain=None),
        "expected.answer_must_contain: required",
    ),
    (
        "inform needs read_calls",
        as_inform,
        lambda d: d["expected"].update(read_calls=[]),
        "expected.read_calls: required",
    ),
    (
        "read_calls only on inform",
        lambda d: d,
        lambda d: d["expected"].update(read_calls=[{"name": "find_patient", "args": {}}]),
        "only inform items have read calls",
    ),
    (
        "answer_must_contain not on none",
        as_none,
        lambda d: d["expected"].update(answer_must_contain=[{"value": 1, "forms": []}]),
        "only inform (and act) items have one",
    ),
    (
        "act expects a write",
        lambda d: d,
        lambda d: d["expected"].update(tool_calls=[]),
        "act items expect at least one write",
    ),
    (
        "none expects no write",
        as_none,
        lambda d: d["expected"].update(
            tool_calls=[{"name": "cancel_appointment", "args": {"appointment_id": "a_9"}}]
        ),
        "none items expect no write",
    ),
    (
        "refuse leaves state unchanged",
        as_refuse,
        lambda d: d["expected"].update(end_state_patch={"appointments[a_9].status": "cancelled"}),
        "refuse items leave the state unchanged",
    ),
    (
        "id carries the domain",
        lambda d: d,
        lambda d: d.update(id="telecom-0042"),
        "must start with the domain",
    ),
    ("changelog ends at revision", lambda d: d, lambda d: d.update(revision=3), "must run 1..3"),
    (
        "changelog dates go forward",
        lambda d: d,
        lambda d: d["changelog"][1].update(date="2026-01-01"),
        "dates must not go backwards",
    ),
    (
        "fixed_after_pilot only for pilot items",
        lambda d: d,
        lambda d: d.update(authoring_batch="post_pilot"),
        "fixed_after_pilot",
    ),
    (
        "tools belong to the domain",
        lambda d: d,
        lambda d: d["tools"].append("recharge"),
        "are not clinic tools",
    ),
    (
        "tools are unique",
        lambda d: d,
        lambda d: d["tools"].append("list_doctors"),
        "tools: duplicate names",
    ),
    (
        "expected writes mutate",
        lambda d: d,
        lambda d: d["expected"]["tool_calls"].append({"name": "find_patient", "args": {}}),
        "'find_patient' does not mutate state",
    ),
    (
        "expected writes are offered",
        lambda d: d,
        lambda d: d["tools"].remove("reschedule_appointment"),
        "'reschedule_appointment' is not in tools",
    ),
    (
        "read calls do not mutate",
        as_inform,
        lambda d: d["expected"].update(read_calls=[{"name": "cancel_appointment", "args": {}}]),
        "'cancel_appointment' mutates state",
    ),
    (
        "must_not_call names offered tools",
        lambda d: d,
        lambda d: d["expected"]["must_not_call"].append("recharge"),
        "'recharge' is not in tools",
    ),
    (
        "expected and forbidden do not clash",
        lambda d: d,
        lambda d: d["expected"]["must_not_call"].append("reschedule_appointment"),
        "both expected and in must_not_call",
    ),
    (
        "insertions only on CS columns",
        lambda d: d,
        lambda d: d["texts"]["egy"].update(insertions=[]),
        "texts.egy.insertions: only cs",
    ),
    (
        "CS columns need insertions",
        lambda d: d,
        lambda d: d["texts"]["cs"].pop("insertions"),
        "texts.cs.insertions: required",
    ),
    (
        "arabizi_profile only on Arabizi columns",
        lambda d: d,
        lambda d: d["texts"]["egy"].update(arabizi_profile="house"),
        "texts.egy.arabizi_profile: only arabizi and cs_latin",
    ),
    (
        "control_of only on act/inform",
        as_refuse,
        lambda d: d.update(control_of="clinic-0043"),
        "only act or inform controls",
    ),
    (
        "control_of is another scenario",
        lambda d: d,
        lambda d: d.update(control_of="clinic-0042"),
        "cannot be its own control twin",
    ),
    (
        "slots carry the intent",
        lambda d: d,
        lambda d: d["slots"].pop("intent"),
        "slots.intent: required",
    ),
    (
        "cultural tags are unique",
        lambda d: d,
        lambda d: d["phenomena"].append("phone_eg"),
        "phenomena: duplicate tags",
    ),
    (
        "orthographic tags are unique",
        lambda d: d,
        lambda d: d["texts"]["msa"]["phenomena"].append("digits_arabic_indic"),
        "texts.msa.phenomena: duplicate tags",
    ),
]


@pytest.mark.parametrize(
    ("base", "mutate", "message"),
    [case[1:] for case in CROSS_FIELD],
    ids=[case[0] for case in CROSS_FIELD],
)
def test_cross_field_rules(
    base: Callable[[Doc], Doc], mutate: Callable[[Doc], object], message: str
) -> None:
    doc = base(example())
    Scenario.model_validate(copy.deepcopy(doc))  # the base itself is valid
    mutate(doc)
    assert message in invalid(doc)


def test_cross_field_problems_are_reported_together() -> None:
    doc = example()
    doc["harm_type"] = "explicit_mismatch"
    doc["texts"]["egy"]["confirm_yes"] = None
    text = invalid(doc)
    assert "harm_type" in text
    assert "texts.egy.confirm_yes" in text
