"""The agent loop: one episode = one scenario text through one provider (docs/harness-spec.md §4).

Rounds. At most `MAX_ROUNDS` (6) completions per user turn; a turn ends when the model returns a
completion without tool calls (the reply). Parallel calls run in order and every result is
appended before the next request; results go back as `ToolMsg(content=record.content)`; an
invented tool gets the sandbox's `unknown_tool` result. The **second** `invalid_arguments` result
for the same tool within a turn ends the turn (`too_many_invalid_calls`, flag `invalid_loop`);
the rest of that completion's calls are not executed. Six completions without a reply end the
turn with flag `round_cap_hit`. `finish_reason == "length"` ends the turn with flag `length`,
plus `truncated_tool_call` when the completion carries tool calls, which are recorded with
`executed: false` and never run. A reply with no content and no calls keeps flag `empty_reply`.

Follow-up rule v1. The column's scripted turn is delivered only when turn 1 ended in a reply with
`finish_reason == "stop"` **and** the behaviour is `act` (→ `confirm_yes`) or `ask`
(→ `follow_up`) **and** no `attempted_write` happened. Nothing follows `invalid_loop`, `length`,
`round_cap_hit`, the deadline or a provider outcome.

Deadline. Summed `latency_ms` of the episode's completions (the recorded latency, so a resume
that replays cached calls ends at the same place) may not reach `DEADLINE_MS` (15 minutes):
the check runs before every request and before the follow-up; when it fires the episode ends
with flag `deadline`.

Errors. `ProviderOutcomeError` ends the episode with that `outcome`; `BudgetExhaustedError`
propagates (the runner stops and the item stays non-terminal). Every episode gets a fresh
sandbox state, and the domain's full tool set is sent on every request.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from afandem.providers.base import (
    AssistantMsg,
    Completion,
    FinishReason,
    JSONDict,
    Message,
    Outcome,
    Provider,
    ProviderOutcomeError,
    Request,
    SystemMsg,
    Target,
    ToolCall,
    ToolMsg,
    UserMsg,
)
from afandem.sandbox import canonical, new_state, registry_for
from afandem.sandbox.tools import ToolRegistry
from afandem.scenarios import Scenario
from afandem.scenarios.schema import Column

MAX_ROUNDS: Final = 6
DEADLINE_MS: Final = 15 * 60 * 1000
FOLLOW_UP_RULE: Final = "v1"

TurnKind = Literal["initial", "confirm_yes", "follow_up"]
TurnEnd = Literal["reply", "length", "too_many_invalid_calls", "round_cap", "deadline"]

FLAG_ORDER: Final = (
    "round_cap_hit",
    "invalid_loop",
    "length",
    "truncated_tool_call",
    "empty_reply",
    "deadline",
    "model_drift",
)
"""Episode flags in their canonical order (`model_drift` is added by the runner)."""


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CallRow(_Row):
    """One tool call as recorded in the trace."""

    turn: int
    round: int
    call_id: str
    name: str
    arguments_raw: str | dict[str, Any]
    arguments_parsed: dict[str, Any] | None
    call_valid: bool
    attempted_write: bool
    mutated: bool
    validity_flags: list[str]
    result: dict[str, Any] | None
    """The sandbox result; None for a call that was not executed."""
    executed: bool = True
    """False only for the calls of a `length` completion (`truncated_tool_call`)."""
    cache_key: str | None = None
    """Cache key of the completion that produced the call."""


class CompletionRow(_Row):
    """One completion's accounting (the trace's `usage` list)."""

    turn: int
    round: int
    finish_reason: FinishReason
    finish_reason_raw: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: float | None
    cost_source: str | None
    latency_ms: int | None
    cache_hit: bool
    cache_key: str | None
    response_id: str | None
    response_model: str | None
    system_fingerprint: str | None
    provider_served: str | None
    tool_calls: int


class TurnRecord(_Row):
    turn: int
    kind: TurnKind
    end: TurnEnd
    rounds: int
    finish_reason: FinishReason | None
    """Finish reason of the turn's last completion (None if no completion was made)."""
    reply: str | None
    """Content of the turn's last completion."""
    text: str
    """Every assistant content of the turn joined with newlines (what `inform` scoring reads)."""


class Episode(BaseModel):
    """Everything one episode did; the runner adds run metadata and scores to make a trace."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    column: Column
    domain: str
    behaviour: str
    messages: list[Message]
    tool_calls: list[CallRow]
    usage: list[CompletionRow]
    turns: list[TurnRecord]
    flags: list[str]
    outcome: Outcome = "ok"
    outcome_detail: str | None = None
    outcome_status: int | None = None
    follow_up_rule: str = FOLLOW_UP_RULE
    follow_up_delivered: bool = False
    state_initial: JSONDict
    state_final: JSONDict
    elapsed_ms: int = 0

    @property
    def finish_reasons(self) -> list[str]:
        return [row.finish_reason for row in self.usage]

    def first_seen(
        self, key: Literal["response_model", "system_fingerprint", "provider_served"]
    ) -> str | None:
        """The first non-null value of a completion field in this episode."""
        return next((value for row in self.usage if (value := getattr(row, key)) is not None), None)

    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)
            order = {name: index for index, name in enumerate(FLAG_ORDER)}
            self.flags.sort(key=lambda name: order.get(name, len(order)))


@dataclass
class _Context:
    episode: Episode
    provider: Provider
    target: Target
    registry: ToolRegistry[Any]
    state: BaseModel
    tools: tuple[JSONDict, ...]
    max_rounds: int
    deadline_ms: int
    messages: list[Message] = field(default_factory=list)

    def past_deadline(self) -> bool:
        return self.episode.elapsed_ms >= self.deadline_ms


def _completion_row(turn: int, round_: int, completion: Completion) -> CompletionRow:
    usage = completion.usage
    return CompletionRow(
        turn=turn,
        round=round_,
        finish_reason=completion.finish_reason,
        finish_reason_raw=completion.finish_reason_raw,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cost_usd=usage.cost_usd,
        cost_source=usage.cost_source,
        latency_ms=completion.latency_ms,
        cache_hit=completion.cache_hit,
        cache_key=completion.cache_key,
        response_id=completion.response_id,
        response_model=completion.response_model,
        system_fingerprint=completion.system_fingerprint,
        provider_served=completion.provider_served,
        tool_calls=len(completion.assistant.tool_calls),
    )


def _truncated_row(turn: int, round_: int, call: ToolCall, cache_key: str | None) -> CallRow:
    parsed: dict[str, Any] | None = None
    if isinstance(call.arguments, dict):
        parsed = dict(call.arguments)
    return CallRow(
        turn=turn,
        round=round_,
        call_id=call.id,
        name=call.name,
        arguments_raw=call.arguments,
        arguments_parsed=parsed,
        call_valid=False,
        attempted_write=False,
        mutated=False,
        validity_flags=["truncated_tool_call"],
        result=None,
        executed=False,
        cache_key=cache_key,
    )


async def _run_turn(ctx: _Context, turn: int, kind: TurnKind, user_text: str) -> TurnRecord:
    episode = ctx.episode
    ctx.messages.append(UserMsg(content=user_text))
    invalid: Counter[str] = Counter()
    replies: list[AssistantMsg] = []
    finish: FinishReason | None = None

    def done(end: TurnEnd, rounds: int) -> TurnRecord:
        last = replies[-1] if replies else None
        return TurnRecord(
            turn=turn,
            kind=kind,
            end=end,
            rounds=rounds,
            finish_reason=finish,
            reply=last.content if last is not None else None,
            text="\n".join(m.content for m in replies if m.content),
        )

    for round_ in range(1, ctx.max_rounds + 1):
        if ctx.past_deadline():
            episode.add_flag("deadline")
            return done("deadline", round_ - 1)
        request = Request(target=ctx.target, messages=tuple(ctx.messages), tools=ctx.tools)
        completion = await ctx.provider.complete(request)
        episode.elapsed_ms += completion.latency_ms or 0
        episode.usage.append(_completion_row(turn, round_, completion))
        assistant = completion.assistant
        ctx.messages.append(assistant)
        replies.append(assistant)
        finish = completion.finish_reason
        if completion.finish_reason == "length":
            episode.add_flag("length")
            if assistant.tool_calls:
                episode.add_flag("truncated_tool_call")
                episode.tool_calls.extend(
                    _truncated_row(turn, round_, call, completion.cache_key)
                    for call in assistant.tool_calls
                )
            return done("length", round_)
        if not assistant.tool_calls:
            if not (assistant.content or "").strip():
                episode.add_flag("empty_reply")
            return done("reply", round_)
        for call in assistant.tool_calls:  # in order; all results before the next request
            record = ctx.registry.execute(ctx.state, call.name, call.arguments)
            ctx.messages.append(
                ToolMsg(tool_call_id=call.id, name=call.name, content=record.content)
            )
            episode.tool_calls.append(
                CallRow(
                    turn=turn,
                    round=round_,
                    call_id=call.id,
                    name=record.name,
                    arguments_raw=record.arguments_raw,
                    arguments_parsed=record.arguments_parsed,
                    call_valid=record.call_valid,
                    attempted_write=record.attempted_write,
                    mutated=record.mutated,
                    validity_flags=list(record.validity_flags),
                    result=dict(record.result),
                    cache_key=completion.cache_key,
                )
            )
            if record.result.get("error") == "invalid_arguments":
                invalid[call.name] += 1
                if invalid[call.name] >= 2:
                    episode.add_flag("invalid_loop")
                    return done("too_many_invalid_calls", round_)
    episode.add_flag("round_cap_hit")
    return done("round_cap", ctx.max_rounds)


def follow_up_due(scenario: Scenario, episode: Episode, turn1: TurnRecord) -> bool:
    """Follow-up rule v1 (plan §2 #4), deadline aside."""
    return (
        turn1.end == "reply"
        and turn1.finish_reason == "stop"
        and scenario.behaviour in ("act", "ask")
        and not any(call.attempted_write for call in episode.tool_calls)
    )


async def run_episode(  # noqa: PLR0913 (the episode's inputs plus its two limits)
    scenario: Scenario,
    column: Column,
    provider: Provider,
    *,
    target: Target,
    system_prompt: str,
    max_rounds: int = MAX_ROUNDS,
    deadline_ms: int = DEADLINE_MS,
) -> Episode:
    """Run one scenario text through `provider` from a fresh sandbox state."""
    state = new_state(
        scenario.domain,
        scenario.initial_state,
        user_identity=scenario.user_identity,
        now=scenario.now.aware,
    )
    registry = registry_for(state)
    initial = canonical(state)
    episode = Episode(
        scenario_id=scenario.id,
        column=column,
        domain=scenario.domain,
        behaviour=scenario.behaviour,
        messages=[],
        tool_calls=[],
        usage=[],
        turns=[],
        flags=[],
        state_initial=initial,
        state_final=initial,
    )
    ctx = _Context(
        episode=episode,
        provider=provider,
        target=target,
        registry=registry,
        state=state,
        tools=tuple(registry.tools_json()),
        max_rounds=max_rounds,
        deadline_ms=deadline_ms,
        messages=[SystemMsg(content=system_prompt)],
    )
    texts = scenario.texts.column(column)
    try:
        turn1 = await _run_turn(ctx, 1, "initial", texts.text)
        episode.turns.append(turn1)
        if follow_up_due(scenario, episode, turn1):
            if ctx.past_deadline():
                episode.add_flag("deadline")
            else:
                episode.follow_up_delivered = True
                if scenario.behaviour == "act":
                    kind: TurnKind = "confirm_yes"
                    text = texts.confirm_yes
                else:
                    kind, text = "follow_up", texts.follow_up
                if text is None:  # the schema requires it; a hand-built scenario may not
                    raise ValueError(f"{scenario.id} {column}: no {kind} text")
                episode.turns.append(await _run_turn(ctx, 2, kind, text))
    except ProviderOutcomeError as exc:
        episode.outcome = exc.outcome
        episode.outcome_detail = exc.detail
        episode.outcome_status = exc.status
    episode.messages = list(ctx.messages)
    episode.state_final = canonical(state)
    return episode


__all__ = [
    "DEADLINE_MS",
    "FLAG_ORDER",
    "FOLLOW_UP_RULE",
    "MAX_ROUNDS",
    "CallRow",
    "CompletionRow",
    "Episode",
    "TurnEnd",
    "TurnKind",
    "TurnRecord",
    "follow_up_due",
    "run_episode",
]
