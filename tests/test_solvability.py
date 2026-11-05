"""Solvability (dataset-spec §2 lint table, harness-spec §10): the discovering oracle, which never
reads `expected`, reaches the expected end state of every `act`/`ask` scenario in data/ and in
the smoke fixtures from the slot table and the tool results alone."""

from pathlib import Path
from typing import Any

import pytest

from afandem.agent.loop import run_episode
from afandem.agent.prompts import PromptSet
from afandem.providers.base import AssistantMsg, Message, ToolCall, ToolMsg, UserMsg
from afandem.providers.discover import (
    DISCOVER_TARGET,
    PLANNERS,
    DiscoveringModel,
    Result,
    results,
)
from afandem.scenarios import Scenario, load_scenarios
from afandem.scenarios.schema import Column
from afandem.scoring import score_episode

ROOT = Path(__file__).parents[1]
SOURCES = [
    ROOT / "data",
    ROOT / "tests" / "fixtures" / "smoke",
    ROOT / "tests" / "fixtures" / "scenarios",
]
ALL = {item.scenario.id: item.scenario for root in SOURCES for item in load_scenarios(root)}
ACTIONABLE = sorted(sid for sid, s in ALL.items() if s.behaviour in ("act", "ask"))
PROMPTS = PromptSet.stub()


def blinded(scenario: Scenario) -> Scenario:
    """The scenario without `expected`: any read of it by the oracle raises."""
    return scenario.model_copy(update={"expected": None})


async def discover(
    scenario: Scenario, column: Column = "egy", model_view: Scenario | None = None
) -> Any:
    model = DiscoveringModel(model_view or blinded(scenario), column)
    episode = await run_episode(
        scenario, column, model, target=DISCOVER_TARGET, system_prompt=PROMPTS.render(scenario)
    )
    return episode, score_episode(scenario, episode)


def test_there_is_something_to_solve() -> None:
    assert {"clinic-0001", "clinic-0007", "clinic-0008", "clinic-9002", "banking-9001"} <= set(
        ACTIONABLE
    )


@pytest.mark.parametrize("scenario_id", ACTIONABLE)
async def test_every_act_and_ask_scenario_is_solvable(scenario_id: str) -> None:
    episode, scores = await discover(ALL[scenario_id])
    assert episode.outcome == "ok" and not episode.flags
    assert scores.task_success is True, scores.reasons
    writes = [c for c in episode.tool_calls if c.attempted_write]
    assert writes and all(c.mutated for c in writes)
    if ALL[scenario_id].behaviour == "ask":
        assert episode.follow_up_delivered and all(c.turn == 2 for c in writes)


@pytest.mark.parametrize("scenario_id", sorted(sid for sid in ALL if sid not in ACTIONABLE))
async def test_other_behaviours_get_a_reply_and_no_call(scenario_id: str) -> None:
    episode, _ = await discover(ALL[scenario_id])
    assert episode.tool_calls == []


async def test_ids_come_from_lookups() -> None:
    episode, _ = await discover(ALL["clinic-9002"])
    names = [c.name for c in episode.tool_calls]
    assert names == ["find_patient", "list_doctors", "book_appointment"]
    assert episode.tool_calls[0].result == {"patient_id": "p_9002"}


async def test_a_lookup_that_finds_nothing_gives_up_with_a_reply() -> None:
    scenario = ALL["clinic-9002"]
    wrong = blinded(scenario).model_copy(
        update={"slots": {**scenario.slots, "phone": "+201000000000"}}
    )
    episode, scores = await discover(scenario, model_view=wrong)
    assert not any(c.attempted_write for c in episode.tool_calls)
    assert scores.task_success is False


async def test_a_transfer_to_an_unknown_account_gives_up() -> None:
    scenario = ALL["banking-9001"]
    wrong = blinded(scenario).model_copy(
        update={"slots": {**scenario.slots, "to_account_id": "acc_x"}}
    )
    episode, _ = await discover(scenario, model_view=wrong)
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
