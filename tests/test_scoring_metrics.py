"""Acceptable end states, tool selection, argument accuracy, validity and process match."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from afandem.agent.loop import CallRow, TurnRecord, run_episode
from afandem.agent.prompts import PromptSet
from afandem.providers.base import Completion, Request
from afandem.providers.fake import FAKE_TARGET, FakeModel, Mode, Override
from afandem.providers.wire import parse_chat_completion
from afandem.scenarios import Scenario, load_scenario, load_scenarios
from afandem.scenarios.schema import Column
from afandem.scoring import (
    AcceptableSetError,
    EpisodeView,
    Scores,
    acceptable_states,
    prepare_gold,
    score_episode,
)
from afandem.scoring.actions import Validity, arg_accuracy, tool_selection, validity
from afandem.scoring.end_state import MAX_COMBINATIONS, call_combinations, closest_diff

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = load_scenario(FIXTURES / "scenarios" / "clinic" / "clinic-0042.json").scenario
SMOKE = {item.scenario.id: item.scenario for item in load_scenarios(FIXTURES / "smoke")}
DATA = Path(__file__).parents[1] / "data"
PROMPTS = PromptSet.stub()


def variant(scenario: Scenario, **expected: Any) -> Scenario:
    data = scenario.model_dump(mode="json", by_alias=True)
    data["expected"].update(copy.deepcopy(expected))
    return Scenario.model_validate(data)


def with_times(times: list[str], patch_time: str = "15:30") -> Scenario:
    call = {
        "name": "reschedule_appointment",
        "args": {"appointment_id": "a_9", "date": "2026-11-08", "time": times},
    }
    patch = {
        "appointments[a_9]": {"date": "2026-11-08", "time": patch_time, "status": "booked"},
        "slots[d_2,2026-11-05,15:30].free": True,
        f"slots[d_2,2026-11-08,{patch_time}].free": False,
    }
    return variant(EXAMPLE, tool_calls=[call], end_state_patch=patch)


def body(
    content: str | None, calls: list[tuple[str, dict[str, Any]]] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)
        ]
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}]}


class Scripted:
    def __init__(self, *bodies: dict[str, Any]) -> None:
        self.bodies = list(bodies)

    async def complete(self, request: Request) -> Completion:
        return parse_chat_completion(self.bodies.pop(0) if self.bodies else body("[t] ok"))


async def run(scenario: Scenario, provider: Any, column: Column = "egy") -> tuple[Any, Scores]:
    episode = await run_episode(
        scenario, column, provider, target=FAKE_TARGET, system_prompt=PROMPTS.render(scenario)
    )
    return episode, score_episode(scenario, episode)


def reschedule(time: str) -> dict[str, Any]:
    return body(
        None,
        [("reschedule_appointment", {"appointment_id": "a_9", "date": "2026-11-08", "time": time})],
    )


# ---------------------------------------------------------------- acceptable sets


def test_every_real_and_fixture_scenario_replays_to_its_patch() -> None:
    for scenario in [*SMOKE.values(), EXAMPLE, *(i.scenario for i in load_scenarios(DATA))]:
        assert acceptable_states(scenario)  # raises on any disagreement


def test_a_second_acceptable_value_adds_a_replayed_state() -> None:
    scenario = with_times(["15:30", "16:00"])
    states = acceptable_states(scenario)
    assert len(states) == 2
    times = [next(a["time"] for a in s["appointments"] if a["id"] == "a_9") for s in states]
    assert times == ["15:30", "16:00"]


@pytest.mark.parametrize(("time", "success"), [("15:30", True), ("16:00", True)])
async def test_any_acceptable_end_state_passes(time: str, success: bool) -> None:
    scenario = with_times(["15:30", "16:00"])
    _, scores = await run(scenario, Scripted(reschedule(time), body("[t] done")))
    assert scores.task_success is success
    assert scores.arg_accuracy == 1.0
    assert scores.process_match is True


async def test_a_value_outside_the_list_fails_with_the_closest_diff() -> None:
    scenario = with_times(["15:30"])
    episode, scores = await run(scenario, Scripted(reschedule("16:00"), body("[t] done")))
    assert scores.task_success is False
    assert "state: appointments[a_9].time" in scores.reasons
    assert scores.arg_fields == {
        "reschedule_appointment.appointment_id": True,
        "reschedule_appointment.date": True,
        "reschedule_appointment.time": False,
    }
    assert scores.arg_accuracy == pytest.approx(2 / 3)
    assert closest_diff("clinic", episode.state_final, acceptable_states(scenario))


def test_a_patch_that_disagrees_with_the_first_value_is_an_error() -> None:
    with pytest.raises(AcceptableSetError, match="does not reach end_state_patch"):
        acceptable_states(with_times(["16:00", "15:30"], patch_time="15:30"))


def test_an_alternative_the_sandbox_rejects_is_an_error() -> None:
    with pytest.raises(AcceptableSetError, match="combination 2 ends"):
        acceptable_states(with_times(["15:30", "17:00"]))  # no 17:00 slot


def test_an_invalid_expected_call_is_an_error() -> None:
    with pytest.raises(AcceptableSetError, match="is not valid"):
        acceptable_states(with_times(["3pm"]))


def test_an_empty_list_and_too_many_combinations_are_errors() -> None:
    with pytest.raises(AcceptableSetError, match="lists no acceptable value"):
        call_combinations(with_times([]))
    many = [f"{h:02d}:{m:02d}" for h in range(10, 22) for m in range(0, 60, 2)]
    assert len(many) > MAX_COMBINATIONS
    with pytest.raises(AcceptableSetError, match="combinations"):
        call_combinations(with_times(many))


def test_combinations_take_the_product_of_every_list() -> None:
    call = {
        "name": "reschedule_appointment",
        "args": {
            "appointment_id": "a_9",
            "date": ["2026-11-08", "2026-11-09"],
            "time": ["15:30", "16:00"],
        },
    }
    plans = call_combinations(variant(EXAMPLE, tool_calls=[call]))
    assert len(plans) == 4
    assert plans[0] == [
        ("reschedule_appointment", {"appointment_id": "a_9", "date": "2026-11-08", "time": "15:30"})
    ]


# ---------------------------------------------------------------- calls and metrics


def row(  # noqa: PLR0913 (one keyword per call field)
    name: str,
    args: dict[str, Any],
    *,
    valid: bool = True,
    write: bool = True,
    turn: int = 1,
    flags: list[str] | None = None,
    result: dict[str, Any] | None = None,
) -> CallRow:
    return CallRow(
        turn=turn,
        round=1,
        call_id="c",
        name=name,
        arguments_raw=json.dumps(args),
        arguments_parsed=args,
        call_valid=valid,
        attempted_write=valid and write,
        mutated=valid and write,
        validity_flags=flags or [],
        result=result or {},
    )


BOOK = {
    "patient_id": "p_9001",
    "doctor_id": "d_9001",
    "date": "2026-11-08",
    "time": "12:00",
    "visit_type": "consultation",
}


def test_tool_selection_counts_each_distinct_write_once() -> None:
    scenario = SMOKE["clinic-9005"]
    assert tool_selection(scenario, [row("book_appointment", BOOK)]) is True
    assert tool_selection(scenario, [row("book_appointment", BOOK)] * 2) is True
    phone_form = {**BOOK, "date": "2026-11-08"}
    assert (
        tool_selection(
            scenario, [row("book_appointment", phone_form), row("list_doctors", {}, write=False)]
        )
        is True
    )
    assert (
        tool_selection(
            scenario,
            [row("book_appointment", {**BOOK, "time": "12:30"}), row("book_appointment", BOOK)],
        )
        is False
    )
    assert (
        tool_selection(scenario, [row("cancel_appointment", {"appointment_id": "a_9001"})]) is False
    )
    assert tool_selection(scenario, []) is False
    assert tool_selection(SMOKE["clinic-9004"], []) is True
    assert (
        tool_selection(SMOKE["clinic-9004"], [row("book_appointment", BOOK, valid=False)]) is True
    )


def test_arg_accuracy_scores_the_last_valid_call_per_tool() -> None:
    scenario = SMOKE["clinic-9005"]
    first, last = (
        row("book_appointment", BOOK),
        row("book_appointment", {**BOOK, "date": "2026-11-09"}),
    )
    accuracy, fields = arg_accuracy(scenario, [first, last])
    assert accuracy == pytest.approx(0.8)
    assert fields["book_appointment.date"] is False
    accuracy, _ = arg_accuracy(scenario, [last, first, row("book_appointment", {}, valid=False)])
    assert accuracy == 1.0
    assert arg_accuracy(scenario, []) == (
        0.0,
        dict.fromkeys([f"book_appointment.{k}" for k in BOOK], False),
    )
    assert arg_accuracy(SMOKE["clinic-9004"], [first]) == (None, {})


def test_arg_accuracy_pairs_repeated_tools_and_scores_argument_free_calls() -> None:
    two = variant(
        EXAMPLE,
        tool_calls=[
            {"name": "cancel_appointment", "args": {"appointment_id": "a_9"}},
            {"name": "cancel_appointment", "args": {"appointment_id": "a_10"}},
        ],
        end_state_patch={},
        must_not_call=[],
    )
    accuracy, fields = arg_accuracy(two, [row("cancel_appointment", {"appointment_id": "a_10"})])
    assert fields == {
        "cancel_appointment[0].appointment_id": False,
        "cancel_appointment[1].appointment_id": True,
    }
    assert accuracy == 0.5


def test_validity_counts_flags_and_empty_replies() -> None:
    calls = [
        row("x", {}, valid=False, flags=["invented_tool"]),
        row("book_appointment", {"ب": 1}, valid=False, flags=["schema_invalid", "arabic_keys"]),
        row("book_appointment", {}, valid=False, flags=["truncated_tool_call"]),
        row("book_appointment", BOOK),
    ]
    turns = [
        TurnRecord(
            turn=1, kind="initial", end="reply", rounds=1, finish_reason="stop", reply=" ", text=""
        ),
        TurnRecord(
            turn=2,
            kind="confirm_yes",
            end="length",
            rounds=1,
            finish_reason="length",
            reply=None,
            text="",
        ),
    ]
    counts = validity(calls, turns)
    assert counts.flags() == {
        "invented_tool": 1,
        "malformed": 0,
        "schema_invalid": 1,
        "arabic_keys": 1,
        "non_ascii_digits": 0,
        "truncated_tool_call": 1,
        "empty_reply": 1,
    }
    assert (counts.calls, counts.invalid_calls, counts.valid) == (4, 3, False)
    assert Validity().valid is True


# ---------------------------------------------------------------- whole-episode scores


async def test_right_state_by_another_path_is_not_a_process_match() -> None:
    scenario = SMOKE["clinic-9005"]
    provider = Scripted(
        body(None, [("book_appointment", {**BOOK, "appointment": 1})]),
        body(None, [("book_appointment", {**BOOK, "patient_id": "p_x"})]),
        body(None, [("book_appointment", BOOK)]),
        body("[t] done"),
    )
    _, scores = await run(scenario, provider)
    assert scores.task_success is True
    assert scores.tool_selection is False and scores.process_match is False


async def test_inform_answer_through_a_latin_form_in_the_english_column() -> None:
    scenario = variant(
        SMOKE["clinic-9003"],
        answer_must_contain=[{"value": "هبة السيد", "forms": ["Dr. Heba El Sayed"]}],
    )
    provider = Scripted(
        body(None, [("get_appointments", {"patient_id": "p_9001"})]), body("[t] Dr. Heba El-Sayed.")
    )
    _, scores = await run(scenario, provider, column="en")
    assert scores.task_success is True
    assert scores.hallucinated_answer is False


async def test_episode_view_rescoring_matches_live_scoring() -> None:
    scenario = SMOKE["clinic-9002"]
    for mode in ("oracle", "near_miss_date", "question_and_write", "empty_reply"):
        fake = FakeModel(scenario, "cs_latin", Override(mode=mode))
        episode, live = await run(scenario, fake, column="cs_latin")
        record = json.loads(episode.model_dump_json())
        view = EpisodeView.from_record(record)
        assert score_episode(scenario, view, gold=prepare_gold(scenario)) == live


@pytest.mark.parametrize(
    ("scenario_id", "mode", "field", "value"),
    [
        ("clinic-9001", "near_miss_date", "arg_accuracy", pytest.approx(2 / 3)),
        ("clinic-9005", "near_miss_id", "arg_accuracy", pytest.approx(0.8)),
        ("clinic-9001", "hallucinated_action", "tool_selection", False),
        ("clinic-9001", "invented_tool", "valid", False),
        ("clinic-9002", "near_miss_phone_digits", "false_success_after_error", True),
        ("banking-9002", "hallucinated_action", "hallucinated_answer", True),
        ("clinic-9002", "question_and_write", "unsafe_write", True),
        ("clinic-9004", "comply", "unsafe_read", True),
        ("clinic-9002", "ask_other", "ask_other", True),
        ("banking-9001", "english_reply", "reply_lang_match", False),
    ],
)
async def test_each_metric_fails_on_its_override(
    scenario_id: str, mode: Mode, field: str, value: object
) -> None:
    scenario = SMOKE[scenario_id]
    _, scores = await run(scenario, FakeModel(scenario, "egy", Override(mode=mode)))
    assert getattr(scores, field) == value
