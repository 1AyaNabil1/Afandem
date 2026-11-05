"""The internal message model shared by every provider, the agent loop, the cache and traces.

Converters sit at the edges (`afandem.providers.wire` for OpenAI-compatible chat completions).
The cache key hashes this model, never SDK or wire objects, so a client-library release cannot
change keys and re-bill a resume.

An assistant turn keeps `wire`: the message exactly as the provider returned it. Providers that
validate their own fields on the way back (Gemini's thought signatures inside
`tool_calls[].extra_content`, OpenRouter's `reasoning_details`) get them back unchanged.

Composition, outermost first, for one target:

    CachedProvider(cache, salt) -> BudgetedProvider(budget) -> HTTP or fake provider

A cache hit never reaches the budget, so `--budget` counts uncached calls only.
"""

import json
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

type JSONDict = dict[str, Any]

FinishReason = Literal["tool_calls", "stop", "length", "content_filter", "error"]
"""Normalised finish reasons. The raw value is kept in `Completion.finish_reason_raw`."""

Outcome = Literal["ok", "provider_error", "quota", "context_overflow", "blocked_by_provider"]
"""Episode outcomes. Everything but `ok` is a harness outcome (docs/harness-spec.md §8):
`provider_error`, `quota` and `context_overflow` are excluded pairwise; `blocked_by_provider`
is a provider-side block, never a model refusal."""

FailureOutcome = Literal["provider_error", "quota", "context_overflow", "blocked_by_provider"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(_Frozen):
    """One tool call as the model produced it."""

    id: str
    name: str
    arguments: str | JSONDict
    """Normally a JSON string, passed to the sandbox untouched (malformed JSON is a finding,
    not an error); a few servers send an object instead."""


class SystemMsg(_Frozen):
    role: Literal["system"] = "system"
    content: str


class UserMsg(_Frozen):
    role: Literal["user"] = "user"
    content: str


class AssistantMsg(_Frozen):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    wire: JSONDict | None = None
    """The message exactly as the provider returned it; None for messages built locally."""


class ToolMsg(_Frozen):
    role: Literal["tool"] = "tool"
    tool_call_id: str
    name: str
    content: str


Message = Annotated[SystemMsg | UserMsg | AssistantMsg | ToolMsg, Field(discriminator="role")]


class Usage(_Frozen):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str | None = None
    """`openrouter_usage`, `price_table:<version>`, `free_tier` or None when unknown."""


class Completion(_Frozen):
    """One model response, normalised; `raw` is the full response body (kept in the cache,
    never written to traces, which carry `cache_key` instead)."""

    assistant: AssistantMsg
    finish_reason: FinishReason
    finish_reason_raw: str | None = None
    usage: Usage = Usage()
    response_id: str | None = None
    response_model: str | None = None
    system_fingerprint: str | None = None
    provider_served: str | None = None
    latency_ms: int | None = None
    cache_key: str | None = None
    cache_hit: bool = False
    raw: JSONDict | None = None


class Target(_Frozen):
    """What one column of results is about: a model reached through one route."""

    name: str
    """Short label used in run directories and tables, e.g. `qwen3.8-27b@groq`."""
    route: str
    """Route id from `config/routes.json`, or `fake`."""
    model: str
    """The model id sent in the request body."""
    params: JSONDict
    """`params_sent`: every body key besides model, messages and tools (temperature,
    max_tokens, tool_choice, reasoning settings ...), exactly as sent."""
    provider_prefs: JSONDict = {}
    """Extra top-level body keys that steer routing (OpenRouter's `provider` object)."""


class Request(_Frozen):
    target: Target
    messages: tuple[Message, ...]
    tools: tuple[JSONDict, ...]
    """Canonical `{name, description, parameters}` dicts (`ToolSpec.as_json()`), sent on every
    request including follow-ups."""


class Provider(Protocol):
    async def complete(self, request: Request) -> Completion: ...


class ProviderOutcomeError(Exception):
    """A call that ended in a harness outcome instead of a completion (after any retries).

    The loop records `outcome` on the episode and ends it. Never raised for model behaviour:
    a refusal, `content_filter` or `length` finish is a completion.
    """

    def __init__(
        self,
        outcome: FailureOutcome,
        detail: str,
        *,
        status: int | None = None,
        body: object = None,
    ) -> None:
        super().__init__(f"{outcome}: {detail}")
        self.outcome: FailureOutcome = outcome
        self.detail = detail
        self.status = status
        self.body = body


class BudgetExhaustedError(Exception):
    """The run's `--budget` of uncached calls is used up; the runner stops cleanly."""


class CallBudget:
    """A count of uncached calls a run may still make (None = unlimited)."""

    def __init__(self, limit: int | None) -> None:
        if limit is not None and limit < 0:
            raise ValueError("budget must be >= 0")
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else self.limit - self.used

    def take(self) -> None:
        if self.limit is not None and self.used >= self.limit:
            raise BudgetExhaustedError(f"budget of {self.limit} uncached call(s) used")
        self.used += 1


class BudgetedProvider:
    """Takes one unit of budget per call that reaches the wrapped provider."""

    def __init__(self, inner: Provider, budget: CallBudget) -> None:
        self.inner = inner
        self.budget = budget

    async def complete(self, request: Request) -> Completion:
        self.budget.take()
        return await self.inner.complete(request)


CANONICAL_SEPARATORS: Final = (",", ":")


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, Arabic unescaped: the form every hash is taken over."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=CANONICAL_SEPARATORS, allow_nan=False
    )


def dump_message(message: SystemMsg | UserMsg | AssistantMsg | ToolMsg) -> JSONDict:
    """The JSON form of an internal message (traces and cache keys)."""
    return message.model_dump(mode="json")


__all__ = [
    "AssistantMsg",
    "BudgetExhaustedError",
    "BudgetedProvider",
    "CallBudget",
    "Completion",
    "FailureOutcome",
    "FinishReason",
    "JSONDict",
    "Message",
    "Outcome",
    "Provider",
    "ProviderOutcomeError",
    "Request",
    "SystemMsg",
    "Target",
    "ToolCall",
    "ToolMsg",
    "Usage",
    "UserMsg",
    "canonical_json",
    "dump_message",
]
