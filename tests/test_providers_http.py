"""The OpenAI-compatible HTTP provider against a scripted fake transport (no network, no sleep).

Every response body below is HAND-WRITTEN from the providers' documented shapes (OpenAI chat
completions, Google's OpenAI-compatible endpoint and google.rpc error details, Groq and
OpenRouter error bodies, Fanar's OpenAPI spec). None is a recorded response: the probe script
records the real ones into tests/fixtures/providers/ once keys exist.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any

import httpx2
import pytest

from afandem.providers.base import (
    AssistantMsg,
    Completion,
    ProviderOutcomeError,
    Request,
    SystemMsg,
    ToolMsg,
    UserMsg,
)
from afandem.providers.http import (
    Hooks,
    OpenAICompatProvider,
    ProviderConfigError,
    RetryEvent,
    RetryPolicy,
    RouteLimiter,
    estimate_tokens,
)
from afandem.providers.routes import RouteConfig, load_routes, resolve_route, target_for

ROUTE = RouteConfig(
    name="test_route",
    label="model@test",
    base_url="https://llm.example.test/v1",
    key_env="TEST_KEY",
    model="vendor/model",
    params={"temperature": 0, "max_tokens": 64, "tool_choice": "auto"},
    free=True,
)
TOOL = {
    "name": "fixture_tool",
    "description": "[fixture tool description]",
    "parameters": {
        "type": "object",
        "properties": {"slot": {"type": "string"}},
        "required": ["slot"],
        "additionalProperties": False,
    },
}
TOOL_RESULT = '{"status":"ok"}'
ENV = {
    "GEMINI_FREE_API_KEY": "k",
    "FANAR_API_KEY": "k",
    "OPENROUTER_API_KEY": "k",
    "GROQ_API_KEY": "k",
}


def _route(name: str) -> RouteConfig:
    return resolve_route(load_routes()[name], {**ENV, "FANAR_MODEL": "", "OLLAMA_MODEL": ""})


def _request(route: RouteConfig = ROUTE, *extra: Any) -> Request:
    messages: tuple[Any, ...] = (
        SystemMsg(content="[fixture system text]"),
        UserMsg(content="[fixture user text]"),
        *extra,
    )
    return Request(target=target_for(route), messages=messages, tools=(TOOL,))


def _ok(message: dict[str, Any] | None = None, finish: str = "stop", **top: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "resp-1",
        "object": "chat.completion",
        "model": "vendor/model-001",
        "choices": [
            {
                "index": 0,
                "message": message or {"role": "assistant", "content": "[fixture reply]"},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }
    body.update(top)
    return body


def _resp(status: int, body: object = None, headers: dict[str, str] | None = None) -> Any:
    def make(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(status, content=body.encode(), headers=headers)
        return httpx2.Response(status, json=body, headers=headers)

    return make


def _raise(exc_type: type[httpx2.TransportError]) -> Any:
    def make(request: httpx2.Request) -> httpx2.Response:
        raise exc_type("[fixture transport failure]", request=request)

    return make


class FakeTime:
    """A clock that only moves when the code under test sleeps (or a response takes time)."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.wall0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC).timestamp()
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def wall_clock(self) -> float:
        return self.wall0 + self.now - 1000.0

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class LowRng(random.Random):
    """random() == 0: jittered backoff is exactly half the exponential step."""

    def random(self) -> float:
        return 0.0


class Server:
    """A scripted `httpx2.MockTransport`: each call consumes the next item."""

    def __init__(self, *items: Callable[[httpx2.Request], httpx2.Response], latency_s: float = 0):
        self.items = list(items)
        self.requests: list[httpx2.Request] = []
        self.started_at: list[float] = []
        self.latency_s = latency_s
        self.time: FakeTime | None = None
        self.transport = httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.time is not None:
            self.started_at.append(self.time.now)
            self.time.now += self.latency_s
        if not self.items:
            raise AssertionError("unexpected extra request")
        return self.items.pop(0)(request)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


def _provider(
    server: Server,
    route: RouteConfig = ROUTE,
    *,
    limiter: RouteLimiter | None = None,
    pacing: dict[str, Any] | None = None,
    api_key: str | None = "test-key",
) -> tuple[OpenAICompatProvider, FakeTime, list[RetryEvent]]:
    clock = FakeTime()
    server.time = clock
    events: list[RetryEvent] = []
    hooks = Hooks(
        sleep=clock.sleep,
        clock=clock.clock,
        wall_clock=clock.wall_clock,
        rng=LowRng(),
        on_event=events.append,
    )
    provider = OpenAICompatProvider(
        route,
        api_key=api_key,
        transport=server.transport,
        hooks=hooks,
        limiter=limiter or RouteLimiter(hooks=hooks, **(pacing or {})),
    )
    return provider, clock, events


async def _outcome(provider: OpenAICompatProvider, request: Request) -> ProviderOutcomeError:
    with pytest.raises(ProviderOutcomeError) as info:
        await provider.complete(request)
    return info.value


# -- the happy path ---------------------------------------------------------------------------


async def test_request_shape_usage_and_latency() -> None:
    server = Server(_resp(200, _ok()), latency_s=1.5)
    provider, _, events = _provider(server)
    completion = await provider.complete(_request())
    request = server.requests[0]
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"
    assert request.method == "POST"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["content-type"] == "application/json"
    body = server.bodies[0]
    assert list(body) == ["model", "messages", "tools", "temperature", "max_tokens", "tool_choice"]
    assert body["tools"][0]["function"]["name"] == "fixture_tool"
    assert completion.assistant.content == "[fixture reply]"
    assert completion.latency_ms == 1500
    assert completion.usage.cost_usd == 0.0
    assert completion.usage.cost_source == "free_tier"
    assert completion.usage.prompt_tokens == 12
    assert completion.provider_served == "test_route"  # no `provider` in the body
    assert completion.raw is not None and completion.raw["id"] == "resp-1"
    assert events == []


async def test_arabic_is_sent_unescaped_and_keyless_route_sends_no_auth() -> None:
    server = Server(_resp(200, _ok()))
    provider, _, _ = _provider(server, api_key=None)
    text = "[fixture user text] " + chr(0x645)
    await provider.complete(
        Request(target=target_for(ROUTE), messages=(UserMsg(content=text),), tools=())
    )
    assert chr(0x645).encode() in server.requests[0].content
    assert b"\\u0645" not in server.requests[0].content
    assert "authorization" not in server.requests[0].headers


def test_unresolved_placeholder_is_refused() -> None:
    with pytest.raises(ValueError, match="placeholders"):
        OpenAICompatProvider(load_routes()["cloudflare_qwen"], api_key="k")


# -- retries ---------------------------------------------------------------------------------


async def test_429_is_retried_with_the_same_model_honouring_retry_after(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = Server(
        _resp(
            429, {"error": {"message": "[fixture] slow down", "code": 429}}, {"Retry-After": "7"}
        ),
        _resp(200, _ok()),
    )
    provider, clock, events = _provider(server)
    with caplog.at_level(logging.WARNING, logger="afandem.providers.http"):
        completion = await provider.complete(_request())
    assert completion.finish_reason == "stop"
    assert [body["model"] for body in server.bodies] == ["vendor/model", "vendor/model"]
    assert server.bodies[0] == server.bodies[1]
    assert clock.sleeps == [7.0]
    assert len(events) == 1
    assert events[0].attempt == 1 and events[0].max_attempts == 5
    assert events[0].status == 429 and events[0].delay_s == 7.0
    assert events[0].model == "vendor/model"
    assert any("attempt 1/5" in record.getMessage() for record in caplog.records)


async def test_retry_after_http_date() -> None:
    clock_probe = FakeTime()
    when = datetime.fromtimestamp(clock_probe.wall_clock() + 30, tz=UTC)
    server = Server(
        _resp(
            503,
            {"error": {"message": "[fixture] overloaded"}},
            {"Retry-After": format_datetime(when, usegmt=True)},
        ),
        _resp(200, _ok()),
    )
    provider, clock, _ = _provider(server)
    await provider.complete(_request())
    assert clock.sleeps == [pytest.approx(30.0)]


async def test_5xx_backoff_is_exponential_and_exhaustion_is_provider_error() -> None:
    server = Server(*[_resp(503, {"error": {"message": "[fixture] unavailable"}})] * 5)
    provider, clock, events = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "provider_error"
    assert "retries exhausted after 5 attempts" in error.detail
    assert error.status == 503
    assert len(server.requests) == 5
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0]  # base 2 s doubling, jitter factor 0.5 here
    assert [event.attempt for event in events] == [1, 2, 3, 4]
    assert {body["model"] for body in server.bodies} == {"vendor/model"}


@pytest.mark.parametrize(
    "failure", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.ConnectError, httpx2.ReadError]
)
async def test_timeouts_and_connection_errors_are_retried(
    failure: type[httpx2.TransportError],
) -> None:
    server = Server(_raise(failure), _resp(200, _ok()))
    provider, clock, events = _provider(server)
    completion = await provider.complete(_request())
    assert completion.finish_reason == "stop"
    assert len(server.requests) == 2
    assert len(clock.sleeps) == 1
    assert events[0].status is None


async def test_too_long_retry_after_ends_the_call() -> None:
    server = Server(_resp(429, {"error": {"message": "[fixture]"}}, {"Retry-After": "3600"}))
    provider, clock, _ = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "provider_error"
    assert "asked to wait 3600s" in error.detail
    assert clock.sleeps == []


async def test_custom_policy_retry_count() -> None:
    server = Server(*[_resp(500, {"error": {"message": "[fixture]"}})] * 2)
    provider, _, _ = _provider(server)
    provider.policy = RetryPolicy(max_retries=1)
    error = await _outcome(provider, _request())
    assert "after 2 attempts" in error.detail


# -- never retried ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 409, 422])
async def test_client_errors_are_provider_errors_without_retry(status: int) -> None:
    server = Server(
        _resp(status, {"error": {"message": "[fixture] bad field xyz", "code": status}})
    )
    provider, clock, events = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "provider_error"
    assert error.status == status
    assert f"HTTP {status}" in error.detail and "bad field xyz" in error.detail
    assert len(server.requests) == 1 and clock.sleeps == [] and events == []


async def test_long_error_body_is_excerpted() -> None:
    server = Server(_resp(400, "x" * 5000))
    provider, _, _ = _provider(server)
    error = await _outcome(provider, _request())
    assert len(error.detail) < 600
    assert error.body == "x" * 5000


async def test_413_is_context_overflow_without_retry() -> None:
    body = {"error": {"code": "too_large", "message": "Request entity too large", "status": 413}}
    server = Server(_resp(413, body))  # Fanar's documented 413
    provider, _, _ = _provider(server, _route("fanar_tools"))
    error = await _outcome(provider, _request(_route("fanar_tools")))
    assert error.outcome == "context_overflow"
    assert len(server.requests) == 1


async def test_groq_413_above_tpm_is_not_context_overflow() -> None:
    body = {
        "error": {
            "message": "Request too large for model `qwen/qwen3.8-27b` in organization `org_x` "
            "service tier `on_demand` on tokens per minute (TPM): Limit 8000, Requested 9100, "
            "please reduce your message size and try again.",
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }
    server = Server(_resp(413, body))
    provider, _, _ = _provider(server, _route("groq_qwen"))
    error = await _outcome(provider, _request(_route("groq_qwen")))
    assert error.outcome == "provider_error"
    assert "tokens-per-minute" in error.detail
    assert len(server.requests) == 1


async def test_openrouter_403_moderation_is_blocked_by_provider() -> None:
    body = {
        "error": {
            "code": 403,
            "message": "[fixture] input was flagged",
            "metadata": {
                "reasons": ["[fixture reason]"],
                "flagged_input": "[fixture user text]",
                "provider_name": "Anthropic",
                "model_slug": "anthropic/claude-sonnet-5.5",
            },
        }
    }
    server = Server(_resp(403, body))
    route = _route("openrouter_sonnet")
    provider, _, events = _provider(server, route)
    error = await _outcome(provider, _request(route))
    assert error.outcome == "blocked_by_provider"
    assert error.status == 403
    assert len(server.requests) == 1 and events == []


async def test_fanar_400_content_filter_is_blocked_by_provider() -> None:
    body = {
        "error": {
            "code": "content_filter",
            "message": "The content was filtered",
            "status": 400,
            "param": "prompt",
            "type": "safety",
        }
    }
    server = Server(_resp(400, body))
    provider, _, _ = _provider(server, _route("fanar_tools"))
    error = await _outcome(provider, _request(_route("fanar_tools")))
    assert error.outcome == "blocked_by_provider"


async def test_groq_tool_use_failed_is_the_models_malformed_call_not_an_error() -> None:
    # Shape recorded live from Groq on 5 Nov 2026 (gpt-oss-120b): HTTP 400, code
    # tool_use_failed, the unparseable generation in failed_generation.
    generation = '{"name": "book_appointment", "arguments": {\n  "date": "2026-10-08",\n ?"}'
    body = {
        "error": {
            "message": "Failed to parse tool call arguments as JSON",
            "type": "invalid_request_error",
            "code": "tool_use_failed",
            "failed_generation": generation,
        }
    }
    server = Server(_resp(400, body))
    provider, _, events = _provider(server, _route("groq_qwen"))
    completion = await provider.complete(_request(_route("groq_qwen")))
    assert len(server.requests) == 1 and events == []  # never retried (no resampling)
    assert completion.finish_reason == "tool_calls"
    assert completion.finish_reason_raw == "tool_use_failed"
    (call,) = completion.assistant.tool_calls
    assert (call.name, call.arguments) == ("book_appointment", generation)
    assert completion.raw == body


async def test_refusal_finish_is_a_completion_not_retried() -> None:
    message = {"role": "assistant", "content": None}
    server = Server(_resp(200, _ok(message, finish="content_filter")))
    provider, clock, _ = _provider(server)
    completion = await provider.complete(_request())
    assert completion.finish_reason == "content_filter"
    assert len(server.requests) == 1 and clock.sleeps == []


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, {"error": {"code": "invalid_authentication", "message": "Invalid authentication"}}),
        (403, {"error": {"code": "invalid_authorization", "message": "Invalid authorization"}}),
        (
            400,
            [
                {
                    "error": {
                        "code": 400,
                        "message": "API key not valid. Please pass a valid API key.",
                        "status": "INVALID_ARGUMENT",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                "reason": "API_KEY_INVALID",
                            }
                        ],
                    }
                }
            ],
        ),
    ],
)
async def test_key_problems_raise_config_error(status: int, body: object) -> None:
    server = Server(_resp(status, body))
    provider, _, _ = _provider(server)
    with pytest.raises(ProviderConfigError) as info:
        await provider.complete(_request())
    assert info.value.status == status
    assert "test-key" not in str(info.value)
    assert len(server.requests) == 1


# -- quota -------------------------------------------------------------------------------------


def _google_429(quota_id: str, retry_delay: str = "41s") -> list[dict[str, Any]]:
    """Google's OpenAI-compatible endpoint wraps the google.rpc error in a list."""
    return [
        {
            "error": {
                "code": 429,
                "message": "[fixture] You exceeded your current quota.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": "generativelanguage.googleapis.com/"
                                "generate_content_free_tier_requests",
                                "quotaId": quota_id,
                                "quotaDimensions": {
                                    "location": "global",
                                    "model": "gemini-3.5-flash-lite",
                                },
                                "quotaValue": "500",
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": retry_delay,
                    },
                ],
            }
        }
    ]


def _groq_429(window: str) -> dict[str, Any]:
    return {
        "error": {
            "message": "Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_x` "
            f"service tier `on_demand` on {window}: Limit 1000, Used 1000, Requested 1. "
            "Please try again in 1m26.4s.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    }


@pytest.mark.parametrize(
    ("route_name", "status", "body"),
    [
        ("gemini_free", 429, _google_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier")),
        ("groq_qwen", 429, _groq_429("requests per day (RPD)")),
        ("groq_qwen", 429, _groq_429("tokens per day (TPD)")),
        ("fanar_tools", 429, {"error": {"code": "exceeded_quota", "message": "Exceeded quota"}}),
        (
            "openrouter_haiku",
            402,
            {"error": {"code": 402, "message": "[fixture] Insufficient credits."}},
        ),
        (
            "openrouter_haiku",
            403,
            {"error": {"code": 403, "message": "[fixture] Key limit exceeded (daily limit)."}},
        ),
    ],
)
async def test_daily_quota_is_quota_immediately(route_name: str, status: int, body: object) -> None:
    route = _route(route_name)
    server = Server(_resp(status, body))
    provider, clock, events = _provider(server, route)
    error = await _outcome(provider, _request(route))
    assert error.outcome == "quota"
    assert len(server.requests) == 1 and clock.sleeps == [] and events == []


async def test_gemini_per_minute_quota_is_retried_after_retry_delay() -> None:
    route = _route("gemini_free")
    body = _google_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "41.5s")
    server = Server(_resp(429, body), _resp(200, _ok()))
    provider, clock, _ = _provider(server, route)
    await provider.complete(_request(route))
    assert clock.sleeps == [41.5]


async def test_groq_per_minute_limit_uses_try_again_hint() -> None:
    route = _route("groq_qwen")
    server = Server(_resp(429, _groq_429("requests per minute (RPM)")), _resp(200, _ok()))
    provider, clock, _ = _provider(server, route)
    await provider.complete(_request(route))
    assert clock.sleeps == [pytest.approx(86.4)]


# -- errors inside HTTP 200 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": 429, "message": "[fixture] upstream rate limited"}},
        {"error": {"code": 502, "message": "[fixture] upstream error"}},
        {"error": {"code": "503", "message": "[fixture] upstream error"}},
        {
            "id": "gen-x",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "error",
                    "error": {"code": 502, "message": "[fixture] provider returned error"},
                }
            ],
        },
    ],
)
async def test_retryable_error_inside_200_is_retried(body: dict[str, Any]) -> None:
    server = Server(_resp(200, body), _resp(200, _ok()))
    provider, clock, events = _provider(server)
    completion = await provider.complete(_request())
    assert completion.finish_reason == "stop"
    assert len(server.requests) == 2 and len(clock.sleeps) == 1
    assert events[0].status == 200


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": 400, "message": "[fixture] invalid"}},
        {"error": "[fixture] something failed"},
        {"choices": []},
        {"id": "x"},
    ],
)
async def test_other_error_inside_200_is_provider_error(body: dict[str, Any]) -> None:
    server = Server(_resp(200, body))
    provider, clock, _ = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "provider_error"
    assert error.status == 200
    assert len(server.requests) == 1 and clock.sleeps == []


async def test_daily_quota_inside_200_is_quota() -> None:
    body = {"error": {"code": 429, "message": "[fixture] tokens per day (TPD) reached"}}
    server = Server(_resp(200, body))
    provider, _, _ = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "quota"


async def test_200_with_non_json_body() -> None:
    server = Server(_resp(200, "<html>[fixture gateway page]</html>"))
    provider, _, _ = _provider(server)
    error = await _outcome(provider, _request())
    assert error.outcome == "provider_error" and "not JSON" in error.detail


# -- the context guard ---------------------------------------------------------------------------


async def test_context_guard_refuses_without_calling() -> None:
    route = _route("fanar_tools")
    assert route.guard_tokens == 7000
    big = Request(
        target=target_for(route),
        messages=(UserMsg(content="[fixture user text] " + "x" * 30_000),),
        tools=(TOOL,),
    )
    server = Server()
    provider, _, _ = _provider(server, route)
    error = await _outcome(provider, big)
    assert error.outcome == "context_overflow"
    assert error.detail.startswith("context_cap:")
    assert server.requests == []


async def test_context_guard_lets_small_prompts_through() -> None:
    route = _route("fanar_tools")
    server = Server(_resp(200, _ok()))
    provider, _, _ = _provider(server, route)
    await provider.complete(_request(route))
    assert len(server.requests) == 1


def test_guard_defaults_to_context_minus_max_tokens() -> None:
    route = ROUTE.model_copy(update={"max_context_tokens": 1000})
    assert route.guard_tokens == 1000 - 64
    assert ROUTE.guard_tokens is None
    assert estimate_tokens("abcdefg") == 3


# -- rate limiting ---------------------------------------------------------------------------------


async def test_rpm_pacer_spaces_request_starts() -> None:
    server = Server(*[_resp(200, _ok())] * 3, latency_s=0.25)
    provider, clock, events = _provider(server, pacing={"rpm": 60})
    for _ in range(3):
        await provider.complete(_request())
    assert server.started_at == [1000.0, 1001.0, 1002.0]
    assert clock.sleeps == [0.75, 0.75]  # pacing waits, not retries
    assert events == []


async def test_rpm_override_reaches_the_shared_limiter() -> None:
    server = Server(*[_resp(200, _ok())] * 2)
    clock = FakeTime()
    server.time = clock
    hooks = Hooks(sleep=clock.sleep, clock=clock.clock, wall_clock=clock.wall_clock)
    route = ROUTE.model_copy(update={"rpm": 60})
    provider = OpenAICompatProvider(
        route, api_key="k", rpm=30, transport=server.transport, hooks=hooks
    )
    await provider.complete(_request())
    await provider.complete(_request())
    assert provider.rpm == 30
    assert provider.limiter().rpm == 30
    assert server.started_at == [1000.0, 1002.0]


async def test_shared_limiter_is_shared_per_route() -> None:
    first = OpenAICompatProvider(ROUTE, api_key="k")
    second = OpenAICompatProvider(ROUTE, api_key="k")
    other = OpenAICompatProvider(ROUTE.model_copy(update={"name": "other"}), api_key="k")
    assert first.limiter() is second.limiter()
    assert first.limiter() is not other.limiter()


async def test_tpm_pacer_waits_for_the_window() -> None:
    clock = FakeTime()
    limiter = RouteLimiter(tpm=1000, hooks=Hooks(sleep=clock.sleep, clock=clock.clock))
    starts: list[float] = []
    for tokens in (600, 600, 300, 2000):
        async with limiter.slot(tokens):
            starts.append(clock.now)
    # 600 at t0; the next 600 would exceed 1000 until t0+60; 300 fits beside it; 2000 alone
    # is above the limit and goes once the window has emptied.
    assert starts == [1000.0, 1060.0, 1060.0, 1120.0]


async def test_tpm_estimate_counts_max_tokens_when_configured() -> None:
    seen: list[int] = []

    class Recording(RouteLimiter):
        def slot(self, tokens: int = 0) -> Any:
            seen.append(tokens)
            return super().slot(tokens)

    route = ROUTE.model_copy(update={"tpm": 8000, "tpm_counts_max_tokens": True})
    server = Server(_resp(200, _ok()), _resp(200, _ok()))
    provider, _, _ = _provider(server, route, limiter=Recording())
    await provider.complete(_request(route))
    plain, _, _ = _provider(server, ROUTE, limiter=Recording())
    await plain.complete(_request())
    payload_tokens = estimate_tokens(server.requests[1].content.decode())
    assert seen == [payload_tokens + 64, payload_tokens]


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_semaphore_bounds_concurrent_requests(concurrency: int) -> None:
    active = 0
    peak = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        for _ in range(5):
            await asyncio.sleep(0)
        active -= 1
        return httpx2.Response(200, json=_ok())

    limiter = RouteLimiter(concurrency=concurrency)
    provider = OpenAICompatProvider(
        ROUTE, api_key="k", transport=httpx2.MockTransport(handler), limiter=limiter
    )
    calls: list[Awaitable[Completion]] = [provider.complete(_request()) for _ in range(4)]
    await asyncio.gather(*calls)
    assert peak == concurrency


# -- passthrough of provider fields ----------------------------------------------------------------


async def test_gemini_thought_signature_round_trips_verbatim() -> None:
    route = _route("gemini_free")
    call = {
        "id": "call-a",
        "type": "function",
        "function": {"name": "fixture_tool", "arguments": '{"slot":"a"}'},
        "extra_content": {"google": {"thought_signature": "c2lnbmF0dXJlLWZpeHR1cmU="}},
    }
    message = {"role": "assistant", "content": None, "tool_calls": [call]}
    server = Server(_resp(200, _ok(message, finish="tool_calls")), _resp(200, _ok()))
    provider, _, _ = _provider(server, route)
    first = await provider.complete(_request(route))
    assert first.assistant.tool_calls[0].name == "fixture_tool"
    follow = _request(
        route,
        first.assistant,
        ToolMsg(tool_call_id="call-a", name="fixture_tool", content=TOOL_RESULT),
    )
    await provider.complete(follow)
    sent = server.bodies[1]["messages"]
    assert sent[2] == message  # the assistant turn exactly as received
    assert sent[3] == {"role": "tool", "tool_call_id": "call-a", "content": TOOL_RESULT}
    assert server.bodies[1]["reasoning_effort"] == "low"


async def test_fanar_legacy_function_call_is_rebuilt_and_tool_name_sent() -> None:
    route = _route("fanar_tools")
    message = {
        "role": "assistant",
        "content": None,
        "function_call": {"name": "fixture_tool", "arguments": '{"slot":"a"}'},
    }
    server = Server(_resp(200, _ok(message, finish="function_call")), _resp(200, _ok()))
    provider, _, _ = _provider(server, route)
    first = await provider.complete(_request(route))
    assert first.finish_reason == "tool_calls"
    assert first.finish_reason_raw == "function_call"
    call = first.assistant.tool_calls[0]
    follow = _request(
        route, first.assistant, ToolMsg(tool_call_id=call.id, name=call.name, content=TOOL_RESULT)
    )
    await provider.complete(follow)
    body = server.bodies[1]
    assert set(body) == {"model", "messages", "tools", "temperature", "max_tokens", "tool_choice"}
    assistant, tool = body["messages"][2], body["messages"][3]
    assert "function_call" not in assistant
    assert assistant["tool_calls"][0]["function"] == {
        "name": "fixture_tool",
        "arguments": '{"slot":"a"}',
    }
    assert tool == {
        "role": "tool",
        "tool_call_id": call.id,
        "content": TOOL_RESULT,
        "name": "fixture_tool",
    }


async def test_openrouter_reasoning_details_echoed_and_cost_recorded() -> None:
    route = _route("openrouter_sonnet")
    details = [{"type": "reasoning.encrypted", "data": "ZmF4dHVyZQ==", "id": "r1", "index": 0}]
    message = {
        "role": "assistant",
        "content": None,
        "reasoning": "[fixture reasoning]",
        "reasoning_details": details,
        "tool_calls": [
            {
                "id": "toolu_1",
                "type": "function",
                "index": 0,
                "function": {"name": "fixture_tool", "arguments": '{"slot":"a"}'},
            }
        ],
    }
    usage = {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49, "cost": 0.000215}
    first_body = _ok(message, finish="tool_calls", provider="Anthropic", usage=usage)
    server = Server(_resp(200, first_body), _resp(200, _ok()))
    provider, _, _ = _provider(server, route)
    first = await provider.complete(_request(route))
    assert first.usage.cost_usd == pytest.approx(0.000215)
    assert first.usage.cost_source == "openrouter_usage"
    assert first.provider_served == "Anthropic"
    follow = _request(
        route,
        first.assistant,
        ToolMsg(tool_call_id="toolu_1", name="fixture_tool", content=TOOL_RESULT),
    )
    await provider.complete(follow)
    body = server.bodies[1]
    assert body["messages"][2]["reasoning_details"] == details
    assert "reasoning" not in body["messages"][2]  # not in the route's echo list
    assert body["provider"] == {
        "order": ["anthropic"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }
    assert body["reasoning"] == {"effort": "low"}
    assert server.requests[0].headers["x-title"] == "afandem"


async def test_locally_built_assistant_message_is_sent() -> None:
    server = Server(_resp(200, _ok()))
    provider, _, _ = _provider(server)
    await provider.complete(_request(ROUTE, AssistantMsg(content="[fixture earlier reply]")))
    assert server.bodies[0]["messages"][2] == {
        "role": "assistant",
        "content": "[fixture earlier reply]",
    }
