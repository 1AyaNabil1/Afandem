"""The agent loop: rounds, limits, flags and every branch of follow-up rule v1."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.agent.loop import DEADLINE_MS, MAX_ROUNDS, Episode, run_episode
from afandem.agent.prompts import PromptSet
from afandem.providers.base import (
    BudgetedProvider,
    BudgetExhaustedError,
    CallBudget,
    Completion,
    ProviderOutcomeError,
    Request,
    ToolMsg,
    UserMsg,
)
from afandem.providers.fake import FAKE_TARGET, FakeModel, Mode, Override
from afandem.providers.http import failed_tool_call
from afandem.providers.wire import parse_chat_completion
from afandem.scenarios import Scenario, load_scenarios
from afandem.scenarios.schema import Column

SMOKE = Path(__file__).parent / "fixtures" / "smoke"
SCENARIOS = {item.scenario.id: item.scenario for item in load_scenarios(SMOKE)}
PROMPTS = PromptSet.stub()


def reply(text: str | None, finish: str = "stop") -> dict[str, Any]:
    return _body({"role": "assistant", "content": text}, finish)


def calls(
    *pairs: tuple[str, object], content: str | None = None, finish: str = "tool_calls"
) -> dict[str, Any]:
    tool_calls = [
        {
            "id": f"c{index}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": args if isinstance(args, str) else json.dumps(args),
            },
        }
        for index, (name, args) in enumerate(pairs)
    ]
    return _body({"role": "assistant", "content": content, "tool_calls": tool_calls}, finish)


def _body(message: dict[str, Any], finish: str) -> dict[str, Any]:
    return {
        "id": "t",
        "model": "test/model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class Scripted:
    """Returns the given response bodies in order, then `[test] done` replies."""

    def __init__(self, *bodies: dict[str, Any], latency_ms: int = 1) -> None:
        self.bodies = list(bodies)
        self.requests: list[Request] = []
        self.latency_ms = latency_ms

    async def complete(self, request: Request) -> Completion:
        self.requests.append(request)
        body = self.bodies.pop(0) if self.bodies else reply("[test] done")
        return parse_chat_completion(body, latency_ms=self.latency_ms)


async def run(
    scenario_id: str,
    provider: Any,
    column: Column = "egy",
    **limits: int,
) -> Episode:
    scenario = SCENARIOS[scenario_id]
    return await run_episode(
        scenario,
        column,
        provider,
        target=FAKE_TARGET,
        system_prompt=PROMPTS.render(scenario),
        **limits,
    )


def fake(
    scenario_id: str, mode: Mode = "oracle", column: Column = "egy", latency: int = 1
) -> FakeModel:
    return FakeModel(SCENARIOS[scenario_id], column, Override(mode=mode, latency_ms=latency))


def user_texts(episode: Episode) -> list[str]:
    return [m.content for m in episode.messages if isinstance(m, UserMsg)]


def texts_of(scenario: Scenario, column: Column = "egy") -> tuple[str, str | None, str | None]:
    block = scenario.texts.column(column)
    return block.text, block.follow_up, block.confirm_yes


# ---------------------------------------------------------------- follow-up rule v1


async def test_act_without_turn1_write_gets_confirm_yes() -> None:
    scenario = SCENARIOS["clinic-9001"]
    provider = Scripted(
        reply("[test] shall I?"),
        calls(
            (
                "reschedule_appointment",
                {"appointment_id": "a_9001", "date": "2026-11-08", "time": "15:30"},
            )
        ),
        reply("[test] done"),
    )
    episode = await run("clinic-9001", provider)
    text, _, confirm = texts_of(scenario)
    assert episode.follow_up_delivered is True
    assert episode.follow_up_rule == "v1"
    assert user_texts(episode) == [text, confirm]
    assert [t.kind for t in episode.turns] == ["initial", "confirm_yes"]


async def test_act_with_turn1_write_gets_no_follow_up() -> None:
    episode = await run("clinic-9001", fake("clinic-9001"))
    assert episode.follow_up_delivered is False
    assert len(user_texts(episode)) == 1
    assert any(call.attempted_write for call in episode.tool_calls)


async def test_ask_without_turn1_write_gets_follow_up() -> None:
    scenario = SCENARIOS["clinic-9002"]
    episode = await run("clinic-9002", fake("clinic-9002"))
    text, follow_up, _ = texts_of(scenario)
    assert episode.follow_up_delivered is True
    assert user_texts(episode) == [text, follow_up]
    assert [t.kind for t in episode.turns] == ["initial", "follow_up"]


async def test_ask_with_turn1_write_gets_no_follow_up() -> None:
    episode = await run("clinic-9002", fake("clinic-9002", "question_and_write"))
    assert episode.follow_up_delivered is False
    assert len(user_texts(episode)) == 1


async def test_a_failed_write_attempt_still_blocks_the_follow_up() -> None:
    """`attempted_write` counts a valid write the sandbox rejected (here `no_slot`)."""
    provider = Scripted(
        calls(
            (
                "reschedule_appointment",
                {"appointment_id": "a_9001", "date": "2026-11-10", "time": "15:30"},
            )
        ),
        reply("[test] could not"),
    )
    episode = await run("clinic-9001", provider)
    assert episode.tool_calls[0].attempted_write and not episode.tool_calls[0].mutated
    assert episode.follow_up_delivered is False


@pytest.mark.parametrize(
    "scenario_id", ["clinic-9003", "clinic-9004", "banking-9003", "banking-9004"]
)
async def test_inform_none_refuse_out_of_scope_end_after_turn1(scenario_id: str) -> None:
    provider = Scripted(reply("[test] reply"))
    episode = await run(scenario_id, provider)
    assert episode.follow_up_delivered is False
    assert len(provider.requests) == 1
    assert [t.end for t in episode.turns] == ["reply"]


@pytest.mark.parametrize(
    ("mode", "flag"),
    [
        ("invalid_loop", "invalid_loop"),
        ("length_mid_call", "length"),
        ("round_cap", "round_cap_hit"),
    ],
)
@pytest.mark.parametrize("scenario_id", ["clinic-9001", "clinic-9002"])
async def test_nothing_follows_a_harness_flag(scenario_id: str, mode: Mode, flag: str) -> None:
    episode = await run(scenario_id, fake(scenario_id, mode))
    assert flag in episode.flags
    assert episode.follow_up_delivered is False
    assert len(user_texts(episode)) == 1


async def test_nothing_follows_a_clipped_reply() -> None:
    episode = await run("clinic-9002", Scripted(reply("[test] which", finish="length")))
    assert episode.flags == ["length"]
    assert "truncated_tool_call" not in episode.flags
    assert episode.follow_up_delivered is False


@pytest.mark.parametrize("finish", ["content_filter", "error"])
async def test_a_reply_not_ending_in_stop_gets_no_follow_up(finish: str) -> None:
    episode = await run("clinic-9001", Scripted(reply("[test] no", finish=finish)))
    assert episode.turns[0].end == "reply"
    assert episode.follow_up_delivered is False


@pytest.mark.parametrize("outcome", ["error_200", "http_403", "quota"])
async def test_nothing_follows_a_provider_outcome(outcome: Mode) -> None:
    episode = await run("clinic-9001", fake("clinic-9001", outcome))
    assert episode.outcome != "ok"
    assert episode.follow_up_delivered is False
    assert episode.turns == []


async def test_empty_reply_with_stop_meets_the_condition_and_keeps_its_flag() -> None:
    episode = await run("clinic-9001", fake("clinic-9001", "empty_reply"))
    assert "empty_reply" in episode.flags
    assert episode.follow_up_delivered is True
    assert episode.turns[1].kind == "confirm_yes"
    assert any(call.mutated for call in episode.tool_calls if call.turn == 2)


async def test_whitespace_reply_is_empty() -> None:
    episode = await run("clinic-9004", Scripted(reply("  \n")))
    assert episode.flags == ["empty_reply"]


# ---------------------------------------------------------------- rounds and limits


async def test_round_cap_is_six_completions() -> None:
    provider = Scripted(*[calls(("list_doctors", {}))] * 10)
    episode = await run("clinic-9001", provider)
    assert len(provider.requests) == MAX_ROUNDS
    assert episode.flags == ["round_cap_hit"]
    assert episode.turns[0].end == "round_cap"
    assert len(episode.tool_calls) == MAX_ROUNDS  # the sixth round's calls still ran


async def test_second_invalid_call_to_the_same_tool_ends_the_turn() -> None:
    bad = {"unexpected": 1}
    provider = Scripted(
        calls(("book_appointment", bad), ("cancel_appointment", bad)),
        calls(
            ("cancel_appointment", {"appointment_id": "a_9001", "extra": 1}), ("list_doctors", {})
        ),
    )
    episode = await run("clinic-9001", provider)
    assert episode.flags == ["invalid_loop"]
    assert episode.turns[0].end == "too_many_invalid_calls"
    names = [call.name for call in episode.tool_calls]
    assert names == ["book_appointment", "cancel_appointment", "cancel_appointment"]
    # the rest of that completion is not executed
    assert "list_doctors" not in names
    assert len(provider.requests) == 2


async def test_invalid_calls_to_different_tools_do_not_loop() -> None:
    provider = Scripted(
        calls(("book_appointment", {"x": 1})),
        calls(("cancel_appointment", {"x": 1})),
        reply("[test] sorry"),
    )
    episode = await run("clinic-9001", provider)
    assert "invalid_loop" not in episode.flags
    assert episode.turns[0].end == "reply"


async def test_unknown_tool_gets_the_sandbox_result_and_does_not_count_as_invalid() -> None:
    provider = Scripted(
        calls(("no_such_tool", {})),
        calls(("no_such_tool", {})),
        reply("[test] ok"),
    )
    episode = await run("clinic-9001", provider)
    assert [c.result for c in episode.tool_calls] == [{"error": "unknown_tool"}] * 2
    assert all("invented_tool" in c.validity_flags for c in episode.tool_calls)
    assert "invalid_loop" not in episode.flags


async def test_parallel_calls_run_in_order_and_all_results_precede_the_next_request() -> None:
    provider = Scripted(
        calls(
            ("list_doctors", {}),
            (
                "reschedule_appointment",
                {"appointment_id": "a_9001", "date": "2026-11-08", "time": "15:30"},
            ),
            ("get_appointments", {"patient_id": "p_9001"}),
        ),
        reply("[test] done"),
    )
    episode = await run("clinic-9001", provider)
    assert [c.name for c in episode.tool_calls] == [
        "list_doctors",
        "reschedule_appointment",
        "get_appointments",
    ]
    assert all(c.round == 1 for c in episode.tool_calls)
    second = provider.requests[1].messages
    results = [m for m in second if isinstance(m, ToolMsg)]
    assert [m.tool_call_id for m in results] == ["c0", "c1", "c2"]
    # the third call saw the state after the second (in-order execution)
    appointments = json.loads(results[2].content)["appointments"]
    assert appointments[0]["date"] == "2026-11-08"


async def test_tool_results_are_the_sandbox_content() -> None:
    episode = await run("clinic-9001", fake("clinic-9001"))
    results = [m for m in episode.messages if isinstance(m, ToolMsg)]
    assert [json.loads(m.content) for m in results] == [c.result for c in episode.tool_calls]


async def test_tools_are_sent_on_every_request_including_the_follow_up() -> None:
    provider = Scripted(reply("[test] which?"), calls(("list_doctors", {})), reply("[test] ok"))
    await run("clinic-9002", provider)
    assert len(provider.requests) == 3
    names = [t["name"] for t in provider.requests[0].tools]
    assert len(names) == 7
    assert all(request.tools == provider.requests[0].tools for request in provider.requests)


async def test_length_with_a_tool_call_does_not_execute_it() -> None:
    episode = await run("clinic-9001", fake("clinic-9001", "length_mid_call"))
    assert episode.flags == ["length", "truncated_tool_call"]
    assert episode.state_final == episode.state_initial
    (call,) = episode.tool_calls
    assert call.executed is False and call.result is None
    assert call.validity_flags == ["truncated_tool_call"]
    assert not any(isinstance(m, ToolMsg) for m in episode.messages)


async def test_deadline_ends_the_episode() -> None:
    episode = await run("clinic-9001", fake("clinic-9001", "round_cap", latency=200_000))
    assert episode.flags == ["deadline"]
    assert episode.elapsed_ms >= DEADLINE_MS
    assert len(episode.usage) == 5  # 5 x 200 s = 1000 s >= 900 s before the sixth request


async def test_deadline_blocks_the_follow_up() -> None:
    episode = await run("clinic-9002", fake("clinic-9002", latency=DEADLINE_MS))
    assert episode.flags == ["deadline"]
    assert episode.follow_up_delivered is False


async def test_no_deadline_under_fifteen_minutes_of_recorded_latency() -> None:
    episode = await run("clinic-9002", fake("clinic-9002", latency=DEADLINE_MS // 4))
    assert episode.flags == []
    assert episode.elapsed_ms == 3 * (DEADLINE_MS // 4)


async def test_provider_outcome_ends_the_episode_with_that_outcome() -> None:
    class Failing:
        async def complete(self, request: Request) -> Completion:
            raise ProviderOutcomeError("blocked_by_provider", "moderated", status=403)

    episode = await run("clinic-9001", Failing())
    assert episode.outcome == "blocked_by_provider"
    assert episode.outcome_status == 403
    assert episode.outcome_detail == "moderated"
    assert episode.state_final == episode.state_initial


async def test_budget_exhaustion_propagates() -> None:
    provider = BudgetedProvider(fake("clinic-9001"), CallBudget(1))
    with pytest.raises(BudgetExhaustedError):
        await run("clinic-9001", provider)


async def test_every_episode_starts_from_a_fresh_state() -> None:
    first = await run("clinic-9005", fake("clinic-9005"))
    second = await run("clinic-9005", fake("clinic-9005"))
    assert first.state_initial == second.state_initial
    assert [c.result for c in first.tool_calls] == [c.result for c in second.tool_calls]
    assert second.tool_calls[0].result is not None
    assert second.tool_calls[0].result["appointment_id"] == "appt_0001"


async def test_records_carry_turn_and_round() -> None:
    episode = await run("clinic-9002", fake("clinic-9002"))
    assert [(u.turn, u.round) for u in episode.usage] == [(1, 1), (2, 1), (2, 2)]
    assert [(c.turn, c.round, c.call_id) for c in episode.tool_calls] == [
        (2, 1, "call_2_1_0"),
        (2, 1, "call_2_1_1"),
    ]
    usage = episode.usage[0]
    assert usage.finish_reason == "stop" and usage.finish_reason_raw == "stop"
    assert usage.response_model == FAKE_TARGET.model
    assert usage.prompt_tokens is not None and usage.latency_ms == 1
    assert episode.finish_reasons == ["stop", "tool_calls", "stop"]


async def test_turn_text_joins_every_assistant_content() -> None:
    provider = Scripted(
        calls(("get_appointments", {"patient_id": "p_9001"}), content="[test] looking"),
        reply("[test] found"),
    )
    episode = await run("clinic-9003", provider)
    assert episode.turns[0].text == "[test] looking\n[test] found"
    assert episode.turns[0].reply == "[test] found"


class FailsOnce:
    """First completion: a server-rejected malformed tool call (Groq `tool_use_failed`)."""

    def __init__(self) -> None:
        self.requests = 0

    async def complete(self, request: Request) -> Completion:
        self.requests += 1
        body = {"error": {"code": "tool_use_failed", "failed_generation": '{"name": "x", "ar'}}
        completion = failed_tool_call(body, 1)
        assert completion is not None
        return completion


async def test_tool_use_failed_is_a_recorded_malformed_call_that_ends_the_turn() -> None:
    provider = FailsOnce()
    episode = await run("clinic-9001", provider)
    assert provider.requests == 1  # the turn ends; no follow-up (no text reply ending in stop)
    assert "tool_use_failed" in episode.flags
    (row,) = episode.tool_calls
    assert row.call_valid is False and row.attempted_write is False
    assert episode.outcome == "ok"
    assert episode.follow_up_delivered is False
