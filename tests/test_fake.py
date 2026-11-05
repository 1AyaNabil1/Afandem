"""FakeModel: the oracle reaches task success, overrides produce their flags and outcomes, and
every near-miss fails."""

import json
from pathlib import Path

import pytest

from afandem.agent.loop import Episode, run_episode
from afandem.agent.prompts import PromptSet
from afandem.providers.base import BudgetedProvider, CallBudget, Request, SystemMsg, UserMsg
from afandem.providers.fake import (
    FAKE_TARGET,
    MODES,
    NEAR_MISSES,
    FakeModel,
    Mode,
    Override,
    OverrideNotApplicableError,
    build_script,
    fake_factory,
    load_overrides,
    override_for,
)
from afandem.scenarios import COLUMNS, load_scenarios
from afandem.scenarios.schema import Column
from afandem.scoring import Scores, expected_state, score_v0

SMOKE = Path(__file__).parent / "fixtures" / "smoke"
SCENARIOS = {item.scenario.id: item.scenario for item in load_scenarios(SMOKE)}
PROMPTS = PromptSet.stub()


async def play(
    scenario_id: str, mode: Mode = "oracle", column: Column = "egy"
) -> tuple[Episode, Scores]:
    scenario = SCENARIOS[scenario_id]
    episode = await run_episode(
        scenario,
        column,
        FakeModel(scenario, column, Override(mode=mode)),
        target=FAKE_TARGET,
        system_prompt=PROMPTS.render(scenario),
    )
    return episode, score_v0(scenario, episode)


def test_the_smoke_suite_covers_the_required_behaviours() -> None:
    seen = {(s.domain, s.behaviour) for s in SCENARIOS.values()}
    for wanted in [
        ("clinic", "act"),
        ("clinic", "ask"),
        ("clinic", "inform"),
        ("clinic", "refuse"),
        ("banking", "act"),
        ("banking", "inform"),
        ("banking", "out_of_scope"),
        ("banking", "none"),
    ]:
        assert wanted in seen


@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
async def test_oracle_reaches_task_success(scenario_id: str, column: Column) -> None:
    episode, scores = await play(scenario_id, column=column)
    assert episode.outcome == "ok"
    assert episode.flags == []
    assert scores.task_success is True, scores.reasons
    assert scores.unsafe_action is False


async def test_ask_oracle_is_not_an_unsafe_action() -> None:
    episode, scores = await play("clinic-9002")
    assert episode.follow_up_delivered is True
    assert not any(c.attempted_write for c in episode.tool_calls if c.turn == 1)
    assert scores.unsafe_write is False
    assert scores.unsafe_action is False
    assert scores.task_success is True


async def test_oracle_goes_through_the_wire_converter() -> None:
    scenario = SCENARIOS["banking-9001"]
    fake = FakeModel(scenario, "arabizi")
    request = Request(
        target=FAKE_TARGET,
        messages=(SystemMsg(content="s"), UserMsg(content="u")),
        tools=({"name": "transfer", "description": "d", "parameters": {"type": "object"}},),
    )
    completion = await fake.complete(request)
    assert completion.raw is not None
    assert completion.raw["object"] == "chat.completion"
    assert completion.assistant.wire is not None
    (call,) = completion.assistant.tool_calls
    assert call.name == "transfer"
    assert json.loads(str(call.arguments)) == {
        "from_account_id": "acc_9001",
        "to_account_id": "acc_9002",
        "amount_egp": 500,
    }
    assert completion.finish_reason == "tool_calls"
    assert completion.provider_served == "fake"
    assert completion.system_fingerprint is not None


async def test_fake_refuses_a_request_without_tools() -> None:
    fake = FakeModel(SCENARIOS["clinic-9001"], "en")
    request = Request(target=FAKE_TARGET, messages=(UserMsg(content="u"),), tools=())
    with pytest.raises(ValueError, match="no tools"):
        await fake.complete(request)


async def test_oracle_uses_the_first_acceptable_value() -> None:
    episode, _ = await play("clinic-9005")
    assert episode.tool_calls[0].arguments_parsed is not None
    assert episode.tool_calls[0].arguments_parsed["visit_type"] == "consultation"


async def test_oracle_verifies_a_third_party_before_writing() -> None:
    episode, _ = await play("clinic-9002")
    assert [c.name for c in episode.tool_calls] == ["find_patient", "book_appointment"]
    assert episode.tool_calls[0].round == episode.tool_calls[1].round


# ---------------------------------------------------------------- overrides


@pytest.mark.parametrize(
    ("mode", "scenario_id", "flag"),
    [
        ("invented_tool", "clinic-9001", "invented_tool"),
        ("arabic_keys", "clinic-9001", "arabic_keys"),
        ("arabic_indic_digits", "clinic-9001", "non_ascii_digits"),
        ("arabic_indic_digits", "banking-9001", "non_ascii_digits"),
    ],
)
async def test_call_level_overrides_set_their_validity_flag(
    mode: Mode, scenario_id: str, flag: str
) -> None:
    episode, scores = await play(scenario_id, mode)
    flagged = [c for c in episode.tool_calls if flag in c.validity_flags]
    assert flagged
    assert not flagged[0].call_valid
    if mode != "invented_tool":
        assert "schema_invalid" in flagged[0].validity_flags
        assert scores.task_success is False


@pytest.mark.parametrize(
    ("mode", "scenario_id", "flags"),
    [
        ("length_mid_call", "clinic-9001", ["length", "truncated_tool_call"]),
        ("length_mid_call", "banking-9003", ["length"]),
        ("empty_reply", "clinic-9004", ["empty_reply"]),
        ("invalid_loop", "banking-9001", ["invalid_loop"]),
        ("invalid_loop", "clinic-9003", ["invalid_loop"]),
        ("round_cap", "clinic-9001", ["round_cap_hit"]),
    ],
)
async def test_episode_overrides_set_their_flag(
    mode: Mode, scenario_id: str, flags: list[str]
) -> None:
    episode, scores = await play(scenario_id, mode)
    assert episode.flags == flags
    if mode in ("length_mid_call", "invalid_loop"):
        assert scores.task_success is False
        assert flags[0] in scores.reasons


@pytest.mark.parametrize(
    ("mode", "outcome", "status"),
    [
        ("error_200", "provider_error", 200),
        ("http_403", "blocked_by_provider", 403),
        ("quota", "quota", 429),
    ],
)
async def test_provider_overrides_set_the_outcome(mode: Mode, outcome: str, status: int) -> None:
    episode, scores = await play("clinic-9001", mode)
    assert episode.outcome == outcome
    assert episode.outcome_status == status
    assert scores.scored is False and scores.task_success is None


async def test_parallel_calls_override_sends_several_calls_in_one_completion() -> None:
    episode, scores = await play("banking-9001", "parallel_calls")
    assert episode.usage[0].tool_calls == 2
    assert [c.name for c in episode.tool_calls] == ["get_balance", "transfer"]
    assert scores.task_success is True


async def test_question_and_write_is_an_unsafe_write_on_ask() -> None:
    episode, scores = await play("clinic-9002", "question_and_write")
    first = episode.usage[0]
    assert first.tool_calls == 2
    assert episode.turns[0].text.startswith("[fake] question")
    assert scores.unsafe_write is True
    assert scores.task_success is False
    assert "write_before_follow_up" in scores.reasons


async def test_english_reply_marks_every_reply() -> None:
    episode, scores = await play("banking-9002", "english_reply", column="egy")
    assert episode.turns[0].reply is not None
    assert episode.turns[0].reply.startswith("[fake en]")
    assert scores.reply_lang_l1 is None  # reply-language scoring is sub-budget (c)


async def test_hallucinated_action_fails_an_act_item() -> None:
    episode, scores = await play("clinic-9001", "hallucinated_action")
    assert episode.follow_up_delivered is True
    assert not any(c.attempted_write for c in episode.tool_calls)
    assert scores.task_success is False


@pytest.mark.xfail(
    strict=True, reason="hallucinated_action detection is deferred to sub-budget (c)"
)
async def test_hallucinated_action_fails_despite_recovery() -> None:
    episode, scores = await play("clinic-9001", "hallucinated_then_recover")
    assert episode.follow_up_delivered is True
    assert any(c.mutated for c in episode.tool_calls if c.turn == 2)
    assert scores.task_success is False


@pytest.mark.parametrize(
    ("mode", "scenario_id"),
    [
        ("near_miss_date", "clinic-9001"),
        ("near_miss_date", "clinic-9002"),
        ("near_miss_date", "clinic-9005"),
        ("near_miss_id", "clinic-9002"),
        ("near_miss_id", "clinic-9005"),
        ("near_miss_id", "banking-9001"),
        ("near_miss_phone_digits", "clinic-9002"),
    ],
)
@pytest.mark.parametrize("column", ["en", "egy", "arabizi"])
async def test_near_misses_fail(mode: Mode, scenario_id: str, column: Column) -> None:
    episode, scores = await play(scenario_id, mode, column)
    assert episode.outcome == "ok"
    assert scores.task_success is False
    assert any(reason.startswith("state: ") for reason in scores.reasons)


async def test_near_miss_date_lands_a_valid_write_on_the_wrong_day() -> None:
    episode, scores = await play("clinic-9001", "near_miss_date")
    (call,) = episode.tool_calls
    assert call.mutated and call.arguments_parsed is not None
    assert call.arguments_parsed["date"] == "2026-11-09"
    assert "state: appointments[a_9001].date" in scores.reasons


async def test_near_miss_id_books_the_wrong_doctor_or_pays_the_wrong_beneficiary() -> None:
    doctor, _ = await play("clinic-9005", "near_miss_id")
    assert doctor.tool_calls[0].mutated
    assert doctor.tool_calls[0].arguments_parsed is not None
    assert doctor.tool_calls[0].arguments_parsed["doctor_id"] == "d_9002"
    payee, _ = await play("banking-9001", "near_miss_id")
    assert payee.tool_calls[0].mutated
    assert payee.tool_calls[0].arguments_parsed is not None
    assert payee.tool_calls[0].arguments_parsed["to_account_id"] == "acc_9003"


async def test_near_miss_phone_digits_fails_the_third_party_check() -> None:
    episode, _ = await play("clinic-9002", "near_miss_phone_digits")
    lookup, booking = episode.tool_calls
    assert "non_ascii_digits" in lookup.validity_flags and not lookup.call_valid
    assert booking.result == {"error": "not_owner"}
    assert booking.attempted_write and not booking.mutated


@pytest.mark.parametrize(
    ("mode", "scenario_id"),
    [
        ("near_miss_date", "banking-9001"),
        ("near_miss_phone_digits", "clinic-9001"),
        ("near_miss_id", "clinic-9004"),
        ("arabic_keys", "clinic-9003"),
        ("parallel_calls", "banking-9003"),
        ("question_and_write", "clinic-9003"),
        ("hallucinated_then_recover", "clinic-9002"),
    ],
)
def test_inapplicable_overrides_are_refused(mode: Mode, scenario_id: str) -> None:
    with pytest.raises(OverrideNotApplicableError):
        build_script(SCENARIOS[scenario_id], mode)


def test_every_mode_is_exercised_here() -> None:
    covered = {
        "oracle",
        "invented_tool",
        "arabic_keys",
        "arabic_indic_digits",
        "parallel_calls",
        "question_and_write",
        "english_reply",
        "length_mid_call",
        "empty_reply",
        "error_200",
        "http_403",
        "quota",
        "invalid_loop",
        "hallucinated_action",
        "hallucinated_then_recover",
        "round_cap",
        *NEAR_MISSES,
    }
    assert covered == set(MODES)


def test_overrides_from_a_file_and_their_precedence(tmp_path: Path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps(
            {
                "*": "http_403",
                "*|en": "quota",
                "clinic-9001": {"mode": "near_miss_date", "latency_ms": 7},
                "clinic-9001|egy": "oracle",
            }
        ),
        encoding="utf-8",
    )
    table = load_overrides(path)
    assert override_for(table, "clinic-9001", "egy").mode == "oracle"
    assert override_for(table, "clinic-9001", "msa") == Override(
        mode="near_miss_date", latency_ms=7
    )
    assert override_for(table, "clinic-9002", "en").mode == "quota"
    assert override_for(table, "clinic-9002", "cs").mode == "http_403"
    assert override_for({}, "clinic-9002", "cs").mode == "oracle"
    assert load_overrides(None) == {}


@pytest.mark.parametrize("bad", [[1], {"*": "no_such_mode"}, {"*": {"mode": "oracle", "x": 1}}])
def test_bad_overrides_are_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        load_overrides(bad)  # type: ignore[arg-type]


async def test_factory_builds_episode_scoped_fakes_and_wraps_them() -> None:
    budget = CallBudget(None)
    factory = fake_factory(
        {"clinic-9001": Override(mode="http_403")},
        wrap=lambda p: BudgetedProvider(p, budget),
    )
    scenario = SCENARIOS["clinic-9005"]
    first, second = factory(scenario, "en", 1), factory(scenario, "en", 1)
    assert first is not second
    episode = await run_episode(
        scenario, "en", first, target=FAKE_TARGET, system_prompt=PROMPTS.render(scenario)
    )
    assert episode.outcome == "ok"
    assert budget.used == 2
    assert expected_state(scenario) != episode.state_initial
