import hashlib
import json
from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from afandem.sandbox import BANKING_TOOLS, CLINIC_TOOLS, canonical, canonical_json, execute
from afandem.sandbox.clinic import ClinicState
from afandem.sandbox.fields import Args
from afandem.sandbox.tools import JSONDict, ToolRegistry, canonical_schema, registry_for

REGISTRIES = (CLINIC_TOOLS, BANKING_TOOLS)

BOOK = {
    "patient_id": "p_17",
    "doctor_id": "d_2",
    "date": "2026-11-08",
    "time": "15:30",
    "visit_type": "consultation",
}


def clinic() -> ClinicState:
    return ClinicState.model_validate(
        {
            "user_identity": {"patient_id": "p_17"},
            "calendar": {"closed": ["Fri"], "hours": [{"open": "10:00", "close": "22:00"}]},
            "patients": [
                {"id": "p_17", "name": "منى محمود عبد الحليم", "phone": "+201000000017"},
                {"id": "p_20", "name": "فاطمة محمد أحمد", "phone": "+201000000020"},
            ],
            "doctors": [
                {"id": "d_2", "name": "د. هبة السيد", "gender": "f", "specialty": "dermatology"}
            ],
            "slots": [
                {"doctor_id": "d_2", "date": "2026-11-08", "time": "15:30"},
                {"doctor_id": "d_2", "date": "2026-11-08", "time": "16:00", "free": False},
            ],
        }
    )


def walk(node: object) -> list[dict[str, Any]]:
    """Every schema object inside a canonical schema (property maps excluded)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    found += walk(sub)
            elif isinstance(value, dict | list):
                found += walk(value)
    elif isinstance(node, list):
        for item in node:
            found += walk(item)
    return found


# --- call levels -------------------------------------------------------------------------


def test_valid_write_that_mutates() -> None:
    state = clinic()
    record = execute(state, "book_appointment", BOOK)
    assert (record.call_valid, record.attempted_write, record.mutated) == (True, True, True)
    assert record.validity_flags == []
    assert record.result["appointment_id"] == "appt_0001"


@pytest.mark.parametrize(
    ("args", "error"),
    [({**BOOK, "time": "16:00"}, "slot_taken"), ({**BOOK, "patient_id": "p_20"}, "not_owner")],
)
def test_valid_write_rejected_by_a_business_rule(args: dict[str, str], error: str) -> None:
    state = clinic()
    before = canonical(state)
    record = execute(state, "book_appointment", args)
    assert record.result == {"error": error}
    assert (record.call_valid, record.attempted_write, record.mutated) == (True, True, False)
    assert canonical(state) == before


def test_valid_read() -> None:
    record = execute(clinic(), "list_doctors", {})
    assert (record.call_valid, record.attempted_write, record.mutated) == (True, False, False)


def test_invalid_arguments() -> None:
    state = clinic()
    before = canonical(state)
    missing = execute(state, "book_appointment", {k: v for k, v in BOOK.items() if k != "time"})
    assert missing.result == {
        "error": "invalid_arguments",
        "detail": [{"code": "missing", "field": "time"}],
    }
    assert (missing.call_valid, missing.attempted_write, missing.mutated) == (False, False, False)
    assert missing.validity_flags == ["schema_invalid"]
    extra = execute(state, "book_appointment", {**BOOK, "notes": "x"})
    assert extra.result["detail"] == [{"code": "extra_forbidden", "field": "notes"}]
    enum = execute(state, "book_appointment", {**BOOK, "visit_type": "checkup"})
    assert enum.result["detail"] == [
        {"code": "literal_error", "field": "visit_type", "allowed": ["consultation", "follow_up"]}
    ]
    bad_date = execute(state, "book_appointment", {**BOOK, "date": "2026-02-30"})
    assert bad_date.result["detail"][0]["field"] == "date"
    assert canonical(state) == before


def test_malformed_and_non_object_arguments() -> None:
    state = clinic()
    broken = execute(state, "book_appointment", '{"patient_id": "p_17",')
    assert broken.result == {"error": "invalid_arguments", "detail": [{"code": "malformed_json"}]}
    assert broken.validity_flags == ["malformed"] and not broken.call_valid
    assert broken.arguments_parsed is None
    for raw in ("[]", "null", '"p_17"'):
        record = execute(state, "find_patient", raw)
        assert record.result["detail"] == [{"code": "not_an_object"}]


def test_json_string_and_dict_arguments_agree() -> None:
    as_text = execute(clinic(), "book_appointment", json.dumps(BOOK, ensure_ascii=False))
    as_dict = execute(clinic(), "book_appointment", BOOK)
    assert as_text.result == as_dict.result
    assert as_text.arguments_parsed == as_dict.arguments_parsed == BOOK
    assert execute(clinic(), "list_doctors", "").call_valid
    assert execute(clinic(), "list_doctors", "  ").call_valid


def test_unknown_tool() -> None:
    state = clinic()
    record = execute(state, "book_doctor", BOOK)
    assert record.result == {"error": "unknown_tool"}
    assert (record.call_valid, record.attempted_write, record.mutated) == (False, False, False)
    assert record.validity_flags == ["invented_tool"]
    assert execute(state, "transfer", "{").validity_flags == ["invented_tool", "malformed"]


def test_arabic_keys_are_flagged_and_invalid() -> None:
    args = {**{k: v for k, v in BOOK.items() if k != "date"}, "التاريخ": "2026-11-08"}
    record = execute(clinic(), "book_appointment", args)
    assert record.validity_flags == ["schema_invalid", "arabic_keys"]
    assert not record.call_valid and not record.attempted_write
    assert {"code": "extra_forbidden", "field": "التاريخ"} in record.result["detail"]
    assert "التاريخ" in record.content


def test_non_ascii_digits_are_flagged_before_validation() -> None:
    record = execute(clinic(), "book_appointment", {**BOOK, "date": "٢٠٢٦-١١-٠٨"})
    assert record.validity_flags == ["schema_invalid", "non_ascii_digits"]
    assert record.result["detail"] == [{"code": "string_pattern_mismatch", "field": "date"}]
    assert not record.call_valid and not record.mutated
    # Free text may carry them: the call is valid, the flag is still recorded.
    free_text = execute(clinic(), "find_patient", {"name": "منى ٢"})
    assert free_text.call_valid and free_text.validity_flags == ["non_ascii_digits"]
    # Phone arguments are structured: ASCII digits only.
    phone = execute(clinic(), "find_patient", {"name": "منى محمود", "phone": "٠١٠٠٠٠٠٠٠١٧"})
    assert not phone.call_valid and phone.validity_flags == ["schema_invalid", "non_ascii_digits"]


def test_strings_are_not_coerced_to_integers() -> None:
    state = clinic()
    record = execute(state, "search_slots", {"doctor_id": 2, "date_from": "x", "date_to": "y"})
    assert not record.call_valid
    assert {d["field"] for d in record.result["detail"]} == {"doctor_id", "date_from", "date_to"}


def test_results_keep_arabic_unescaped() -> None:
    record = execute(clinic(), "list_doctors", {})
    assert "د. هبة السيد" in record.content
    assert "\\u0" not in record.content
    assert json.loads(record.content) == record.result


def test_record_keeps_raw_arguments_and_copies_parsed_ones() -> None:
    args: dict[str, Any] = dict(BOOK)
    record = execute(clinic(), "book_appointment", args)
    args["time"] = "16:00"
    assert record.arguments_raw == BOOK and record.arguments_parsed == BOOK
    text = '{"name": "منى محمود"}'
    assert execute(clinic(), "find_patient", text).arguments_raw == text


# --- canonical state -----------------------------------------------------------------------


def test_canonical_state_is_order_insensitive_and_skips_the_session() -> None:
    state = clinic()
    shuffled = state.model_copy(deep=True)
    shuffled.slots.reverse()
    shuffled.patients.reverse()
    assert canonical(state) == canonical(shuffled)
    assert canonical_json(state) == canonical_json(shuffled)
    assert "session" not in canonical(state)
    execute(state, "find_patient", {"name": "فاطمة محمد أحمد", "phone": "01000000020"})
    assert state.session.verified_patient_ids == ["p_20"]
    assert canonical(state) == canonical(shuffled)


# --- schemas ---------------------------------------------------------------------------------


class Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


class Point(BaseModel):
    x: int
    y: int


class NestedArgs(Args):
    title: str
    colour: Colour
    point: Point
    tags: list[Colour] = Field(default_factory=list)
    note: str | None = Field(default=None, description="free text")


def test_canonical_schema_inlines_defs_and_strips_titles() -> None:
    raw = NestedArgs.model_json_schema()
    assert "$defs" in raw
    canon = canonical_schema(raw)
    text = json.dumps(canon)
    assert "$ref" not in text and "$defs" not in text and "anyOf" not in text
    assert all("title" not in node for node in walk(canon))
    assert "title" in canon["properties"]  # a property may be called title
    assert canon["properties"]["colour"] == {"enum": ["red", "blue"], "type": "string"}
    assert canon["properties"]["tags"]["items"] == {"enum": ["red", "blue"], "type": "string"}
    assert canon["properties"]["point"]["additionalProperties"] is False
    assert canon["properties"]["note"] == {"description": "free text", "type": "string"}
    assert canon["required"] == ["colour", "point", "title"]
    assert canon["additionalProperties"] is False
    for node in walk(canon):
        assert list(node) == sorted(node)
        if "properties" in node:
            assert list(node["properties"]) == sorted(node["properties"])


@pytest.mark.parametrize("registry", REGISTRIES, ids=lambda r: r.domain)
def test_every_tool_schema_is_flat_and_canonical(registry: ToolRegistry[Any]) -> None:
    for spec in registry:
        schema = spec.parameters
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text and "anyOf" not in text
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert all("title" not in node for node in walk(schema))
        assert json.dumps(schema) == json.dumps(schema, sort_keys=True)
        assert all(not isinstance(p.get("type"), list) for p in schema["properties"].values())
        assert spec.description and spec.description.isascii()
        assert schema == canonical_schema(spec.args_model.model_json_schema())


@pytest.mark.parametrize("registry", REGISTRIES, ids=lambda r: r.domain)
def test_tool_snapshot_hash_is_stable(registry: ToolRegistry[Any]) -> None:
    first = registry.tools_canonical_json()
    assert first == registry.tools_canonical_json()
    assert json.loads(first) == json.loads(json.dumps(registry.tools_json(), sort_keys=True))
    digest = hashlib.sha256(first.encode()).hexdigest()
    assert digest == hashlib.sha256(registry.tools_canonical_json().encode()).hexdigest()
    names = [tool["name"] for tool in registry.tools_json()]
    assert names == registry.names() and len(names) <= 8


# --- the decorator ---------------------------------------------------------------------------


class GuardState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter: int = 0


GUARDS: ToolRegistry[GuardState] = ToolRegistry("guards", GuardState)


class StepArgs(Args):
    by: int = Field(default=1, ge=1)


@GUARDS.tool(mutates=True)
def step(state: GuardState, args: StepArgs) -> JSONDict:
    """Add to the counter."""
    state.counter += args.by
    return {"counter": state.counter}


def test_decorated_tools_keep_their_types_and_run_directly() -> None:
    state = GuardState()
    assert step(state, StepArgs(by=2)) == {"counter": 2}
    assert GUARDS["step"].mutates and GUARDS["step"].description == "Add to the counter."
    assert registry_for(state) is GUARDS
    assert execute(state, "step", {}).mutated


def test_decorator_guards() -> None:
    class LaxArgs(BaseModel):
        by: int = 1

    with pytest.raises(TypeError, match="extra='forbid'"):

        @GUARDS.tool(mutates=False)
        def lax(state: GuardState, args: LaxArgs) -> JSONDict:
            """Doc."""
            return {}

    with pytest.raises(TypeError, match="docstring"):

        @GUARDS.tool(mutates=False)
        def undocumented(state: GuardState, args: StepArgs) -> JSONDict:
            return {}

    with pytest.raises(TypeError, match=r"\(state, args\)"):

        @GUARDS.tool(mutates=False)
        def misnamed(st: GuardState, args: StepArgs) -> JSONDict:
            """Doc."""
            return {}

    with pytest.raises(TypeError, match="state must be"):

        @GUARDS.tool(mutates=False)  # type: ignore[arg-type]
        def wrong_state(state: ClinicState, args: StepArgs) -> JSONDict:
            """Doc."""
            return {}

    with pytest.raises(ValueError, match="twice"):
        GUARDS.tool(mutates=True)(step)

    with pytest.raises(ValueError, match="already has"):
        ToolRegistry("again", GuardState)


def test_registry_for_unknown_state() -> None:
    class Loose(BaseModel):
        pass

    with pytest.raises(KeyError):
        registry_for(Loose())
