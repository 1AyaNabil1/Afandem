"""The end-state patch applier, key derivation and the state diff."""

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from afandem.sandbox import DOMAINS, canonical, new_state
from afandem.scenarios import Scenario, load_scenario, load_scenarios
from afandem.scoring.end_state import (
    COMPOSITE_KEYS,
    PatchError,
    apply_patch,
    expected_state,
    key_fields,
    parse_path,
    state_diff,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = load_scenario(FIXTURES / "scenarios" / "clinic" / "clinic-0042.json").scenario
SMOKE = {item.scenario.id: item.scenario for item in load_scenarios(FIXTURES / "smoke")}


def initial(scenario: Scenario) -> dict[str, Any]:
    state = new_state(
        scenario.domain,
        scenario.initial_state,
        user_identity=scenario.user_identity,
        now=scenario.now.aware,
    )
    return canonical(state)


def with_patch(scenario: Scenario, patch: dict[str, Any]) -> Scenario:
    data = scenario.model_dump(mode="json", by_alias=True)
    data["expected"]["end_state_patch"] = patch
    return Scenario.model_validate(data)


def test_parse_path() -> None:
    assert parse_path("appointments[a_9]") == [("appointments", "a_9")]
    assert parse_path("slots[d_2,2026-11-08,15:30].free") == [
        ("slots", "d_2,2026-11-08,15:30"),
        ("free", None),
    ]
    assert parse_path("calendar.ramadan") == [("calendar", None), ("ramadan", None)]
    assert parse_path("accounts[EG.EXT-1].balance_piastres") == [
        ("accounts", "EG.EXT-1"),
        ("balance_piastres", None),
    ]


@pytest.mark.parametrize("bad", ["", "a..b", "a[]", "a[x]b", "1a", "a.", "a[x][y]"])
def test_bad_paths_are_errors(bad: str) -> None:
    with pytest.raises(PatchError, match="bad patch path"):
        parse_path(bad)


def test_the_spec_example_patch() -> None:
    before = initial(EXAMPLE)
    after = expected_state(EXAMPLE)
    (appointment,) = after["appointments"]
    assert appointment["date"] == "2026-11-08" and appointment["time"] == "15:30"
    slots = {(s["date"], s["time"]): s["free"] for s in after["slots"]}
    assert slots == {
        ("2026-11-05", "15:30"): True,
        ("2026-11-08", "15:30"): False,
        ("2026-11-08", "16:00"): True,
    }
    assert state_diff("clinic", after, before) == [
        "appointments[a_9].date",
        "slots[d_2,2026-11-05,15:30].free",
        "slots[d_2,2026-11-08,15:30].free",
    ]


def test_empty_patch_means_unchanged() -> None:
    for scenario_id in ("clinic-9003", "clinic-9004", "banking-9003"):
        scenario = SMOKE[scenario_id]
        assert expected_state(scenario) == initial(scenario)


def test_created_record_takes_its_key_fields_from_the_key_and_defaults_from_the_model() -> None:
    patch = {
        "appointments[appt_0001]": {
            "patient_id": "p_17",
            "doctor_id": "d_2",
            "date": "2026-11-08",
            "time": "16:00",
            "visit_type": "consultation",
        },
        "slots[d_2,2026-11-08,16:00].free": False,
        "slots[d_2,2026-11-09,10:00]": {"free": True},
    }
    after = expected_state(with_patch(EXAMPLE, patch))
    created = next(a for a in after["appointments"] if a["id"] == "appt_0001")
    assert created["status"] == "booked"  # the model's default
    new_slot = next(s for s in after["slots"] if s["date"] == "2026-11-09")
    assert new_slot == {"doctor_id": "d_2", "date": "2026-11-09", "time": "10:00", "free": True}


def test_a_dict_value_merges_into_an_existing_record() -> None:
    doc = initial(EXAMPLE)
    out = apply_patch("clinic", doc, {"appointments[a_9]": {"status": "cancelled"}})
    (appointment,) = out["appointments"]
    assert appointment["status"] == "cancelled"
    assert appointment["date"] == "2026-11-05"  # untouched fields kept
    assert doc["appointments"][0]["status"] == "booked"  # the input is not modified


def test_top_level_and_nested_fields() -> None:
    doc = initial(EXAMPLE)
    out = apply_patch("clinic", doc, {"calendar.ramadan": True, "next_id": 9})
    assert out["calendar"]["ramadan"] is True
    assert out["next_id"] == 9


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"slots[d_2,2026-11-05]": {"free": True}}, "the key is doctor_id,date,time"),
        ({"appointments[a_404].status": "cancelled"}, "no record appointments"),
        ({"appointments[a_9]": "cancelled"}, "takes an object"),
        ({"calendar[x]": {"a": 1}}, "only top-level collections"),
        ({"patients[p_17].aliases[0]": "x"}, "only top-level collections"),
        ({"nothing.here": 1}, "no field 'nothing'"),
        ({"calendar.closed.Fri": 1}, "is not inside an object"),
    ],
)
def test_patch_errors(patch: dict[str, Any], message: str) -> None:
    with pytest.raises(PatchError, match=message):
        apply_patch("clinic", initial(EXAMPLE), patch)


@pytest.mark.parametrize(
    "patch",
    [
        {"appointments[a_9].colour": "red"},  # unknown field
        {"slots[d_2,2026-11-05,15:30].free": True},  # booked appointment in a free slot
    ],
)
def test_a_patch_that_breaks_the_state_is_an_error(patch: dict[str, Any]) -> None:
    with pytest.raises(PatchError, match="patched state is invalid"):
        expected_state(with_patch(EXAMPLE, patch))


def test_key_fields_cover_every_record_collection() -> None:
    """Every list of records in a domain state has an `id` or a composite key."""
    for domain, (state_type, _) in DOMAINS.items():
        for name, info in state_type.model_fields.items():
            args: tuple[object, ...] = getattr(info.annotation, "__args__", ())
            item = args[0] if len(args) == 1 else None
            if isinstance(item, type) and issubclass(item, BaseModel):
                fields = key_fields(domain, name)
                assert set(fields) <= set(item.model_fields), (domain, name)
    assert COMPOSITE_KEYS["clinic"]["slots"] == ("doctor_id", "date", "time")
    assert key_fields("banking", "cards") == ("last4",)
    assert key_fields("banking", "beneficiaries") == ("owner_id", "account_id")
    assert key_fields("banking", "transactions") == ("id",)
    with pytest.raises(PatchError):
        key_fields("clinic", "calendar")


def test_banking_patch_names_the_generated_transaction() -> None:
    after = expected_state(SMOKE["banking-9001"])
    (transaction,) = after["transactions"]
    assert transaction["id"] == "txn_0001"
    assert transaction["date"] == "2026-11-04"  # the state's `today`
    assert transaction["note"] is None
    balances = {a["id"]: a["balance_piastres"] for a in after["accounts"]}
    assert balances["acc_9001"] == 1_950_000 and balances["acc_9002"] == 1_050_000


def test_composite_keys_for_cards_and_beneficiaries() -> None:
    scenario = SMOKE["banking-9001"]
    doc = initial(scenario)
    out = apply_patch(
        "banking",
        doc,
        {
            "cards[9001].status": "blocked",
            "cards[9001].block_reason": "lost",
            "beneficiaries[c_9001,acc_9003].bank": "other",
        },
    )
    assert out["cards"][0]["status"] == "blocked"
    beneficiary = next(b for b in out["beneficiaries"] if b["account_id"] == "acc_9003")
    assert beneficiary["bank"] == "other"


def test_state_diff_ignores_next_id_and_a_free_note() -> None:
    expected = expected_state(SMOKE["banking-9001"])
    actual = copy.deepcopy(expected)
    actual["next_id"] = 7
    actual["transactions"][0]["note"] = "any text the model chose"
    assert state_diff("banking", actual, expected) == []


def test_state_diff_compares_an_expected_note() -> None:
    expected = expected_state(SMOKE["banking-9001"])
    expected["transactions"][0]["note"] = "rent"
    actual = copy.deepcopy(expected)
    actual["transactions"][0]["note"] = "other"
    assert state_diff("banking", actual, expected) == ["transactions[txn_0001].note"]
    actual["transactions"][0]["note"] = None
    assert state_diff("banking", actual, expected) == ["transactions[txn_0001].note"]


def test_state_diff_reports_extra_and_missing_records() -> None:
    expected = expected_state(SMOKE["clinic-9005"])
    base = initial(SMOKE["clinic-9005"])
    assert state_diff("clinic", base, expected) == [
        "appointments[appt_0001] (missing)",
        "slots[d_9001,2026-11-08,12:00].free",
    ]
    assert state_diff("clinic", expected, base) == [
        "appointments[appt_0001] (extra)",
        "slots[d_9001,2026-11-08,12:00].free",
    ]


def test_state_diff_on_unkeyed_values() -> None:
    a = initial(EXAMPLE)
    b = copy.deepcopy(a)
    b["calendar"]["ramadan"] = True
    assert state_diff("clinic", a, b) == ["calendar"]
    del b["calendar"]
    assert state_diff("clinic", a, b) == ["calendar"]
