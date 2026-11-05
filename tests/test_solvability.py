"""Solvability (dataset-spec §2 lint table, harness-spec §10): the discovering oracle, which never
reads `expected`, reaches the expected end state of every `act`/`ask` scenario, and the answer of
every `inform` scenario, in data/ and in the fixtures from the slot table and the tool results
alone. Constructed scenarios keep the smoke fixtures' placeholder texts."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.providers.base import AssistantMsg, Message, ToolCall, ToolMsg, UserMsg
from afandem.providers.discover import (
    PLANNERS,
    READERS,
    REPLY_ANSWER,
    Result,
    answer,
    blinded,
    results,
    solve,
)
from afandem.scenarios import COLUMNS, Scenario, load_scenarios

ROOT = Path(__file__).parents[1]
SMOKE = ROOT / "tests" / "fixtures" / "smoke"
SOURCES = [ROOT / "data", SMOKE, ROOT / "tests" / "fixtures" / "scenarios"]
ALL = {item.scenario.id: item.scenario for root in SOURCES for item in load_scenarios(root)}
ACTIONABLE = sorted(sid for sid, s in ALL.items() if s.behaviour in ("act", "ask"))
INFORM = sorted(sid for sid, s in ALL.items() if s.behaviour == "inform")
SOLVED = {*ACTIONABLE, *INFORM}


def test_there_is_something_to_solve() -> None:
    assert {"clinic-0001", "clinic-0007", "clinic-0008", "clinic-9002", "banking-9001"} <= set(
        ACTIONABLE
    )
    assert {"clinic-0004", "clinic-0005", "clinic-9003", "banking-9002"} <= set(INFORM)


@pytest.mark.parametrize("scenario_id", ACTIONABLE)
async def test_every_act_and_ask_scenario_is_solvable(scenario_id: str) -> None:
    episode, scores = await solve(ALL[scenario_id])
    assert episode.outcome == "ok" and not episode.flags
    assert scores.task_success is True, scores.reasons
    writes = [c for c in episode.tool_calls if c.attempted_write]
    assert writes
    if ALL[scenario_id].expected.end_state_patch:
        assert all(c.mutated for c in writes)
    else:  # an over-limit transfer: the attempted write is the gold, and the sandbox rejects it
        assert all((c.result or {}).get("error") == "limit_exceeded" for c in writes)
    if ALL[scenario_id].behaviour == "ask":
        assert episode.follow_up_delivered and all(c.turn == 2 for c in writes)


@pytest.mark.parametrize("scenario_id", INFORM)
async def test_every_inform_scenario_is_answered_from_the_reads(scenario_id: str) -> None:
    episode, scores = await solve(ALL[scenario_id])
    assert episode.outcome == "ok" and not episode.flags
    assert scores.task_success is True, scores.reasons
    assert episode.tool_calls and all(c.call_valid for c in episode.tool_calls)
    assert not any(c.attempted_write for c in episode.tool_calls)


@pytest.mark.parametrize("scenario_id", sorted(sid for sid in ALL if sid not in SOLVED))
async def test_other_behaviours_get_a_reply_and_no_call(scenario_id: str) -> None:
    episode, _ = await solve(ALL[scenario_id])
    assert episode.tool_calls == []


async def test_ids_come_from_lookups() -> None:
    episode, _ = await solve(ALL["clinic-9002"])
    names = [c.name for c in episode.tool_calls]
    assert names == ["find_patient", "list_doctors", "book_appointment"]
    assert episode.tool_calls[0].result == {"patient_id": "p_9002"}


async def test_a_lookup_that_finds_nothing_gives_up_with_a_reply() -> None:
    scenario = ALL["clinic-9002"]
    wrong = blinded(scenario).model_copy(
        update={"slots": {**scenario.slots, "phone": "+201000000000"}}
    )
    episode, scores = await solve(scenario, model_view=wrong)
    assert not any(c.attempted_write for c in episode.tool_calls)
    assert scores.task_success is False


async def test_a_transfer_to_an_unknown_account_gives_up() -> None:
    scenario = ALL["banking-9001"]
    wrong = blinded(scenario).model_copy(
        update={"slots": {**scenario.slots, "to_account_id": "acc_x"}}
    )
    episode, _ = await solve(scenario, model_view=wrong)
    assert [c.name for c in episode.tool_calls] == ["list_beneficiaries"]


def test_results_pair_calls_with_their_tool_messages() -> None:
    messages: list[Message] = [
        UserMsg(content="u"),
        AssistantMsg(
            content=None,
            tool_calls=(
                ToolCall(id="1", name="list_doctors", arguments="{}"),
                ToolCall(id="2", name="x", arguments={"a": 1}),
            ),
        ),
        ToolMsg(tool_call_id="1", name="list_doctors", content='{"doctors": []}'),
        ToolMsg(tool_call_id="2", name="x", content="[1]"),
        ToolMsg(tool_call_id="9", name="y", content="{}"),
    ]
    found = results(messages)
    assert [(r.name, r.args, r.result) for r in found] == [
        ("list_doctors", {}, {"doctors": []}),
        ("x", {"a": 1}, {}),
    ]


# ---------------------------------------------------------------- planner branches


def with_slots(scenario_id: str, **slots: Any) -> Scenario:
    return blinded(ALL[scenario_id]).model_copy(update={"slots": slots})


def done(name: str, result: dict[str, Any]) -> list[Result]:
    return [Result(name, {}, result)]


def test_clinic_planner_branches() -> None:
    plan = PLANNERS["clinic"]
    unknown = with_slots("clinic-9005", intent="say_hello")
    assert plan(unknown, []) is None
    earliest = with_slots("clinic-9005", intent="book_earliest", specialty="dermatology")
    (search,) = plan(earliest, []) or []
    assert search.name == "search_slots" and search.args == {
        "specialty": "dermatology",
        "date_from": "2026-11-04",
        "date_to": "2026-12-04",
    }
    assert plan(earliest, done("search_slots", {"slots": []})) is None
    two = {"doctors": [{"doctor_id": "d_1", "gender": "f"}, {"doctor_id": "d_2", "gender": "m"}]}
    book = {"intent": "book", "specialty": "dermatology", "date": "2026-11-08", "time": "12:00"}
    by_gender = with_slots("clinic-9005", **book, doctor_gender="m")
    (call,) = plan(by_gender, done("list_doctors", two)) or []
    assert call.name == "book_appointment" and isinstance(call.args, dict)
    assert call.args["doctor_id"] == "d_2"
    either = with_slots("clinic-9005", **book)
    (search,) = plan(either, done("list_doctors", two)) or []
    assert search.name == "search_slots"
    both_free = {
        "slots": [{"doctor_id": d, "date": "2026-11-08", "time": "12:00"} for d in ("d_1", "d_2")]
    }
    history = [*done("list_doctors", two), *done("search_slots", both_free)]
    assert plan(either, history) is None
    named = with_slots("clinic-9005", **book, doctor_id="d_1")
    (call,) = plan(named, history) or []
    assert isinstance(call.args, dict) and call.args["doctor_id"] == "d_1"
    third = with_slots(
        "clinic-9002", intent="book_third_party", patient_id="p_9002", phone="+201000009002"
    )
    assert plan(third, done("find_patient", {"error": "not_found"})) is None
    move = with_slots("clinic-9001", intent="reschedule", appointment_date="2026-11-30")
    listed = {
        "appointments": [
            {"appointment_id": "a_9001", "date": "2026-11-05", "time": "15:30", "status": "booked"}
        ]
    }
    assert plan(move, done("get_appointments", listed)) is None
    assert plan(move, done("reschedule_appointment", {})) is None


def test_banking_planner_branches() -> None:
    plan = PLANNERS["banking"]
    block = with_slots("banking-9001", intent="block_card", card_last4="9001", reason="lost")
    (call,) = plan(block, []) or []
    assert call.name == "block_card" and call.args == {"card_last4": "9001", "reason": "lost"}
    assert plan(block, done("block_card", {})) is None
    assert plan(with_slots("banking-9001", intent="loan"), []) is None
    scenario = ALL["banking-9001"]
    accounts = [
        *scenario.initial_state["accounts"],
        {**scenario.initial_state["accounts"][0], "id": "acc_extra"},
    ]
    two_own = blinded(scenario).model_copy(
        update={
            "slots": {"intent": "transfer", "to_account_id": "acc_9002", "amount_egp": 5},
            "initial_state": {**scenario.initial_state, "accounts": accounts},
        }
    )
    assert plan(two_own, []) is None  # no source named and more than one own account


def calls(plan: Any) -> list[tuple[str, Any]]:
    return [(call.name, call.args) for call in plan or []]


def test_banking_transfer_destination_branches() -> None:
    plan = PLANNERS["banking"]
    scenario = ALL["banking-9001"]
    own = {**scenario.initial_state["accounts"][0], "id": "acc_9004", "balance_piastres": 0}
    to_own = blinded(scenario).model_copy(
        update={
            "slots": {**scenario.slots, "to_account_id": "acc_9004"},
            "initial_state": {
                **scenario.initial_state,
                "accounts": [*scenario.initial_state["accounts"], own],
            },
        }
    )
    args = {"from_account_id": "acc_9001", "to_account_id": "acc_9004", "amount_egp": 500}
    assert calls(plan(to_own, [])) == [("transfer", args)]  # own accounts need no lookup (D23)
    by_name = blinded(scenario)
    ambiguous = done("list_beneficiaries", {"ambiguous": ["acc_9002", "acc_9003"]})
    assert plan(by_name, ambiguous) is None
    assert plan(by_name, done("list_beneficiaries", {"error": "not_found"})) is None
    no_source = with_slots(
        "banking-9001", intent="transfer", to_account_id="acc_9002", amount_egp=5
    )
    lookup = [("list_beneficiaries", {"account_id": "acc_9001", "name": "Epsilon Placeholder"})]
    assert calls(plan(no_source, [])) == lookup  # the source is the customer's only account
    no_amount = with_slots("banking-9001", intent="transfer", to_account_id="acc_9002")
    assert plan(no_amount, []) is None
    assert plan(with_slots("banking-9001", intent="block_card"), []) is None  # no reason


def test_banking_reads_follow_the_intent() -> None:
    read = READERS["banking"]
    account = {"account_id": "acc_9001"}
    assert calls(read(with_slots("banking-9002", intent="balance"), [])) == [
        ("get_balance", account)
    ]
    assert calls(read(with_slots("banking-9002", intent="list_beneficiaries"), [])) == [
        ("list_beneficiaries", account)
    ]
    dated = with_slots("banking-9002", intent="last_transaction", date="2026-11-02")
    window = {"date_from": "2026-11-02", "date_to": "2026-11-02"}
    assert calls(read(dated, [])) == [("list_transactions", {**account, **window})]
    undated = with_slots("banking-9002", intent="transfer_status", account_id="acc_9001")
    month = {"date_from": "2026-10-05", "date_to": "2026-11-04"}
    assert calls(read(undated, [])) == [("list_transactions", {**account, **month})]
    made = [Result("get_balance", account, {"balance_egp": 1})]
    assert read(with_slots("banking-9002", intent="balance"), made) is None
    scenario = ALL["banking-9002"]
    accounts = [
        *scenario.initial_state["accounts"],
        {**scenario.initial_state["accounts"][0], "id": "acc_extra"},
    ]
    two_own = blinded(scenario).model_copy(
        update={
            "slots": {"intent": "balance"},
            "initial_state": {**scenario.initial_state, "accounts": accounts},
        }
    )
    assert read(two_own, []) is None  # which account? the slot table must say


def test_clinic_reads_follow_the_slot_table() -> None:
    read = READERS["clinic"]
    own = with_slots("clinic-9003", intent="appointment_date", patient_id="p_9001")
    assert calls(read(own, [])) == [("get_appointments", {"patient_id": "p_9001"})]
    earliest = with_slots("clinic-9005", intent="earliest_slot", specialty="dermatology")
    window = {"date_from": "2026-11-04", "date_to": "2026-12-04"}
    assert calls(read(earliest, [])) == [
        ("search_slots", {"specialty": "dermatology", **window}),
        ("list_doctors", {"specialty": "dermatology"}),
    ]
    third = with_slots(
        "clinic-9002", intent="appointment_date", patient_id="p_9002", phone="+201000009002"
    )
    (lookup,) = calls(read(third, []))
    assert lookup[0] == "find_patient"
    found = done("find_patient", {"patient_id": "p_9002"})
    assert calls(read(third, found)) == [("get_appointments", {"patient_id": "p_9002"})]
    assert read(with_slots("clinic-9005", intent="opening_hours"), []) is None


def test_the_inform_reply_carries_the_read_results() -> None:
    reply = answer([Result("get_balance", {}, {"balance_egp": 200})])
    assert reply == f'{REPLY_ANSWER} [{{"balance_egp": 200}}]'


# ---------------------------------------------------------------- banking end to end


def banking_doc(behaviour: str = "act") -> dict[str, Any]:
    """banking-9001 (a transfer to a saved beneficiary; placeholder texts)."""
    path = SMOKE / "banking" / "banking-9001.json"
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    doc["behaviour"] = behaviour
    if behaviour != "act":
        for name in COLUMNS:
            doc["texts"][name]["confirm_yes"] = None
    return doc


@pytest.mark.parametrize(
    ("given", "query"),
    [
        ({"phone": "+201000009012"}, {"phone": "+201000009012"}),
        ({}, {"name": "Epsilon Placeholder"}),
    ],
)
async def test_a_transfer_finds_the_beneficiary_by_phone_or_name(
    given: dict[str, Any], query: dict[str, Any]
) -> None:
    doc = banking_doc()
    doc["slots"].update(given)
    episode, scores = await solve(Scenario.model_validate(doc))
    assert scores.task_success is True, scores.reasons
    lookup, transfer = episode.tool_calls
    assert lookup.name == "list_beneficiaries"
    assert lookup.arguments_parsed == {"account_id": "acc_9001", **query}
    assert lookup.result == {
        "beneficiaries": [{"account_id": "acc_9002", "name": "Epsilon Placeholder"}]
    }
    assert transfer.name == "transfer" and transfer.mutated


@pytest.mark.parametrize(
    "slots",
    [
        {"intent": "block_card", "card_last4": "9001", "reason": "lost"},
        {"intent": "block_card", "reason": "lost"},  # the only card, listed in the policy block
    ],
)
async def test_block_card_is_solvable(slots: dict[str, Any]) -> None:
    doc = banking_doc()
    doc["slots"] = slots
    doc["expected"].update(
        tool_calls=[{"name": "block_card", "args": {"card_last4": "9001", "reason": "lost"}}],
        end_state_patch={"cards[9001].status": "blocked", "cards[9001].block_reason": "lost"},
        must_not_call=["transfer"],
    )
    episode, scores = await solve(Scenario.model_validate(doc))
    assert scores.task_success is True, scores.reasons
    assert [c.name for c in episode.tool_calls] == ["block_card"]


def transactions_item(value: int) -> Scenario:
    doc = banking_doc("inform")
    doc["initial_state"]["transactions"] = [
        {
            "id": "txn_0100",
            "date": "2026-11-02",
            "kind": "transfer",
            "from_account_id": "acc_9001",
            "to_account_id": "acc_9003",
            "amount_piastres": 75000,
            "counterparty": "Zeta Placeholder",
        }
    ]
    doc["slots"] = {"intent": "last_transfer", "account_id": "acc_9001"}
    window = {"date_from": "2026-10-05", "date_to": "2026-11-04"}
    doc["expected"].update(
        tool_calls=[],
        end_state_patch={},
        must_not_call=["transfer", "block_card"],
        read_calls=[{"name": "list_transactions", "args": {"account_id": "acc_9001", **window}}],
        answer_must_contain=[{"value": value, "forms": [str(value)]}],
    )
    return Scenario.model_validate(doc)


async def test_an_inform_item_is_answered_only_from_what_a_tool_returns() -> None:
    episode, scores = await solve(transactions_item(750))
    assert scores.task_success is True, scores.reasons
    assert [c.name for c in episode.tool_calls] == ["list_transactions"]
    _, unreachable = await solve(transactions_item(999))
    assert unreachable.task_success is False
    assert unreachable.reasons == ["answer_missing"]
