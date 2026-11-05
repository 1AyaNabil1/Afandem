"""The OpenAI-compatible HTTP provider: one route, raw JSON in and out.

The request body comes from `wire.request_body` and the response is parsed from the raw JSON
by `wire.parse_chat_completion`, never through typed SDK models (they drop fields such as
Gemini's `extra_content` thought signatures). Transport: an `httpx2` async client (the HTTP
library under the `openai` SDK); tests inject an `httpx2.MockTransport`.

Reliability policy (docs/harness-spec.md §5, docs/providers.md):

- Retried, same model, up to 4 times with exponential backoff and jitter: HTTP 429 (unless
  it names a daily quota), 408, 5xx, timeouts, connection errors, and errors inside an HTTP
  200 whose code is 429 or 5xx. `Retry-After` (seconds or HTTP-date), Google's `retryDelay`
  and "try again in ..." hints are honoured.
- Never retried: 400, 404, 413, 422 (`provider_error`, or `context_overflow` for 413);
  a daily-quota 429 or 402 (`quota`); a moderation 403 (`blocked_by_provider`); any other
  401/403 raises `ProviderConfigError`, which stops the run. Refusals are completions.
- A route with a context cap refuses locally above its guard (chars/3 estimate) with
  `context_overflow` and a `context_cap:` detail, without calling.
- Pacing is shared per route within the process: a semaphore, an rpm pacer (minimum
  interval between request starts) and an optional tpm pacer fed by the same estimate.
"""

import asyncio
import email.utils
import json
import logging
import math
import random
import re
import time
import weakref
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any, Final

import httpx2

from afandem import __version__
from afandem.providers import wire
from afandem.providers.base import (
    AssistantMsg,
    Completion,
    FailureOutcome,
    JSONDict,
    ProviderOutcomeError,
    Request,
    ToolCall,
)
from afandem.providers.routes import RouteConfig

USER_AGENT: Final = f"afandem/{__version__}"

logger = logging.getLogger(__name__)

EXCERPT_CHARS: Final = 500
CHARS_PER_TOKEN: Final = 3

type Sleep = Callable[[float], Awaitable[None]]
type Clock = Callable[[], float]


class ProviderConfigError(Exception):
    """A configuration problem (key rejected, model not authorised, bad URL) that should stop
    the run rather than be recorded as an episode outcome."""

    def __init__(
        self, route: str, detail: str, *, status: int | None = None, body: object = None
    ) -> None:
        super().__init__(f"route {route!r}: {detail}")
        self.route = route
        self.detail = detail
        self.status = status
        self.body = body


@dataclass(frozen=True)
class RetryEvent:
    """Reported through `on_event` (and logged) before every retry."""

    route: str
    model: str
    attempt: int
    """1-based number of the attempt that failed."""
    max_attempts: int
    reason: str
    status: int | None
    delay_s: float


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 4
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0
    max_wait_s: float = 300.0
    """Longest provider-requested wait honoured; a longer one ends the call (provider_error)."""


async def _asyncio_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass
class Hooks:
    """Injectable time, randomness and event reporting (tests never really wait)."""

    sleep: Sleep = _asyncio_sleep
    clock: Clock = time.monotonic
    wall_clock: Clock = time.time
    rng: random.Random = field(default_factory=random.Random)
    on_event: Callable[[RetryEvent], None] | None = None


def estimate_tokens(payload: str) -> int:
    """The prompt-size estimate used by the context guard and the tpm pacer: chars / 3."""
    return math.ceil(len(payload) / CHARS_PER_TOKEN)


# -- rate limiting ------------------------------------------------------------------------


class RouteLimiter:
    """Concurrency, requests-per-minute and tokens-per-minute pacing for one route."""

    def __init__(
        self,
        *,
        concurrency: int = 1,
        rpm: float | None = None,
        tpm: int | None = None,
        hooks: Hooks | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        hooks = hooks or Hooks()
        self.concurrency = concurrency
        self.rpm = rpm
        self.tpm = tpm
        self._clock = hooks.clock
        self._sleep = hooks.sleep
        self._semaphore = asyncio.Semaphore(concurrency)
        self._interval = 60.0 / rpm if rpm else 0.0
        self._next_start: float | None = None
        self._window: deque[tuple[float, int]] = deque()
        self._pace_lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, tokens: int = 0) -> AsyncIterator[None]:
        """Hold one concurrency slot; the request may start when this is entered."""
        async with self._semaphore:
            await self._pace(tokens)
            yield

    def _wait_s(self, now: float, tokens: int) -> float:
        wait = 0.0 if self._next_start is None else self._next_start - now
        if self.tpm is not None:
            while self._window and self._window[0][0] <= now - 60.0:
                self._window.popleft()
            used = sum(count for _, count in self._window)
            if self._window and used + tokens > self.tpm:
                wait = max(wait, self._window[0][0] + 60.0 - now)
        return wait

    async def _pace(self, tokens: int) -> None:
        if not self._interval and self.tpm is None:
            return
        async with self._pace_lock:
            while True:
                now = self._clock()
                wait = self._wait_s(now, tokens)
                if wait <= 0:
                    break
                await self._sleep(wait)
            if self._interval:
                self._next_start = now + self._interval
            if self.tpm is not None:
                if tokens > self.tpm:
                    logger.warning(
                        "request estimate %d tokens exceeds the route's %d TPM", tokens, self.tpm
                    )
                self._window.append((now, tokens))


type _LimiterKey = tuple[str, int, float | None, int | None]
_LIMITERS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[_LimiterKey, RouteLimiter]] = (
    weakref.WeakKeyDictionary()
)


def shared_limiter(
    route: str,
    *,
    concurrency: int,
    rpm: float | None,
    tpm: int | None,
    hooks: Hooks | None = None,
) -> RouteLimiter:
    """The process-wide limiter for a route (per event loop): every provider built for the
    same route with the same limits shares one semaphore and one pacer."""
    per_loop = _LIMITERS.setdefault(asyncio.get_running_loop(), {})
    key = (route, concurrency, rpm, tpm)
    limiter = per_loop.get(key)
    if limiter is None:
        limiter = RouteLimiter(concurrency=concurrency, rpm=rpm, tpm=tpm, hooks=hooks)
        per_loop[key] = limiter
    return limiter


# -- error classification -------------------------------------------------------------------


@dataclass(frozen=True)
class _Retry:
    reason: str
    status: int | None
    body: object = None
    hint_s: float | None = None


_DAILY_TEXT: Final = re.compile(r"\b(?:requests|tokens) per day\b|\b(?:RPD|TPD)\b", re.IGNORECASE)
_CREDIT_TEXT: Final = re.compile(
    r"key limit|limit exceeded|insufficient credits|more credits|credit limit", re.IGNORECASE
)
_BAD_KEY_TEXT: Final = re.compile(
    r"API key not valid|API_KEY_INVALID|invalid api key|invalid_api_key", re.IGNORECASE
)
_DURATION_PART: Final = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_TRY_AGAIN: Final = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", re.IGNORECASE)
_UNIT_S: Final = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT_CHARS else flat[:EXCERPT_CHARS] + "..."


def _error_object(body: object) -> JSONDict:
    """The error object of `{"error": {...}}`, Google's `[{"error": {...}}]`, or a bare one."""
    if isinstance(body, list) and body and isinstance(body[0], dict):
        body = body[0]
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    if isinstance(error, dict):
        return error
    if isinstance(error, str):
        return {"message": error}
    if "message" in body or "code" in body:
        return body
    return {}


def _walk(value: object) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _duration_s(text: str) -> float | None:
    parts = _DURATION_PART.findall(text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        return None
    return sum(float(number) * _UNIT_S[unit] for number, unit in parts)


def _retry_after_header(headers: Mapping[str, str], wall_now: float) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, when.timestamp() - wall_now)


def _retry_hint(
    headers: Mapping[str, str], body: object, message: str, wall_now: float
) -> float | None:
    """Retry-After, else Google's `retryDelay`, else a "try again in 1m26.4s" message."""
    header = _retry_after_header(headers, wall_now)
    if header is not None:
        return header
    for item in _walk(body):
        delay = item.get("retryDelay")
        if isinstance(delay, str):
            parsed = _duration_s(delay.strip())
            if parsed is not None:
                return parsed
    match = _TRY_AGAIN.search(message)
    return _duration_s(match.group(1)) if match else None


def _daily_quota(error: Mapping[str, Any], body: object, message: str) -> str | None:
    for item in _walk(body):
        quota_id = item.get("quotaId")
        if isinstance(quota_id, str) and "PerDay" in quota_id:
            return f"daily quota exhausted ({quota_id})"
    if _DAILY_TEXT.search(message):
        return f"daily quota exhausted: {_excerpt(message)}"
    if error.get("code") == "exceeded_quota":  # Fanar
        return f"quota exhausted: {_excerpt(message)}"
    return None


def _moderation(error: Mapping[str, Any]) -> bool:
    metadata = error.get("metadata")
    return isinstance(metadata, dict) and (
        "reasons" in metadata or any(str(key).startswith("flagged") for key in metadata)
    )


def _tpm_request_too_large(error: Mapping[str, Any], message: str) -> bool:
    """Groq answers a single request above the per-minute token limit with a 413."""
    return (
        error.get("code") == "rate_limit_exceeded"
        or error.get("type") == "tokens"
        or "tokens per minute" in message.lower()
    )


def _int_code(code: object) -> int | None:
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    if isinstance(code, str) and code.strip().isdigit():
        return int(code.strip())
    return None


@dataclass(frozen=True)
class ErrorResponse:
    """A non-2xx response as the classifier sees it."""

    status: int
    body: object
    """Parsed JSON, or the text when the body is not JSON."""
    text: str
    headers: Mapping[str, str]


type _Decision = _Retry | ProviderOutcomeError | ProviderConfigError


@dataclass(frozen=True)
class _Failure:
    route: str
    response: ErrorResponse
    error: Mapping[str, Any]
    message: str
    wall_now: float

    @property
    def detail(self) -> str:
        return f"HTTP {self.response.status}: {_excerpt(self.response.text)}"

    def outcome(self, kind: FailureOutcome, what: str | None = None) -> ProviderOutcomeError:
        return ProviderOutcomeError(
            kind, what or self.detail, status=self.response.status, body=self.response.body
        )

    def retry(self) -> _Retry:
        hint = _retry_hint(self.response.headers, self.response.body, self.message, self.wall_now)
        return _Retry(self.detail, self.response.status, self.response.body, hint)

    def config(self, what: str) -> ProviderConfigError:
        return ProviderConfigError(
            self.route,
            f"{what}, {self.detail}",
            status=self.response.status,
            body=self.response.body,
        )


def _on_429(failure: _Failure) -> _Decision:
    daily = _daily_quota(failure.error, failure.response.body, failure.message)
    if daily is not None:
        return failure.outcome("quota", f"HTTP 429, {daily}")
    return failure.retry()


def _on_auth(failure: _Failure) -> _Decision:
    status = failure.response.status
    excerpt = _excerpt(failure.response.text)
    if status == 403 and _moderation(failure.error):
        return failure.outcome("blocked_by_provider", f"HTTP 403 moderation: {excerpt}")
    if status == 402 or _CREDIT_TEXT.search(failure.message):
        return failure.outcome("quota", f"HTTP {status} (credits or key limit): {excerpt}")
    return failure.config("key rejected or not authorised")


def _on_413(failure: _Failure) -> _Decision:
    if _tpm_request_too_large(failure.error, failure.message):
        return failure.outcome(
            "provider_error",
            "HTTP 413, request above the tokens-per-minute limit: "
            + _excerpt(failure.response.text),
        )
    return failure.outcome("context_overflow")


def _on_400(failure: _Failure) -> _Decision:
    if _BAD_KEY_TEXT.search(failure.response.text):
        return failure.config("key rejected")
    code = failure.error.get("code")
    if code == "content_filter":  # Fanar's documented provider-side filter
        return failure.outcome(
            "blocked_by_provider", f"HTTP 400 content filter: {_excerpt(failure.response.text)}"
        )
    if code == "context_length_exceeded":
        return failure.outcome("context_overflow")
    return failure.outcome("provider_error")


TOOL_USE_FAILED: Final = "tool_use_failed"
_CALL_NAME = re.compile(r'"name"\s*:\s*"([^"]+)"')


def failed_tool_call(body: object, latency_ms: int | None) -> Completion | None:
    """A tool call the server could not parse, returned as the model's completion.

    Groq answers a generated tool call that is not valid JSON with HTTP 400, error code
    `tool_use_failed` and the raw text in `failed_generation` (5 Nov 2026 probe). That is the
    model's output, not a provider failure: excluding it would hide model failures, and it may
    be column-asymmetric. It becomes one malformed call (name parsed when possible, arguments =
    the raw generation) with `finish_reason_raw = "tool_use_failed"`; the loop records it, flags
    the episode and ends the turn, and the cache keeps it like any completion.
    """
    error = _error_object(body)
    if error.get("code") != TOOL_USE_FAILED:
        return None
    generation = str(error.get("failed_generation") or "")
    match = _CALL_NAME.search(generation)
    call = ToolCall(id=TOOL_USE_FAILED, name=match.group(1) if match else "", arguments=generation)
    return Completion(
        assistant=AssistantMsg(content=None, tool_calls=(call,)),
        finish_reason="tool_calls",
        finish_reason_raw=TOOL_USE_FAILED,
        latency_ms=latency_ms,
        raw=dict(body) if isinstance(body, Mapping) else {"body": body},
    )


def classify_http_error(route: str, response: ErrorResponse, wall_now: float) -> _Decision:
    """Map a non-2xx response to a retry, a harness outcome or a configuration error."""
    error = _error_object(response.body)
    message = str(error.get("message") or response.text)
    failure = _Failure(route, response, error, message, wall_now)
    status = response.status
    if status == 429:
        return _on_429(failure)
    if status in (401, 402, 403):
        return _on_auth(failure)
    if status == 413:
        return _on_413(failure)
    if status == 400:
        return _on_400(failure)
    if status == 408 or status >= 500:
        return failure.retry()
    return failure.outcome("provider_error")


def classify_embedded_error(
    error: wire.EmbeddedError, wall_now: float
) -> _Retry | ProviderOutcomeError:
    """An error inside an HTTP 200: retried only for code 429 (not daily) or 5xx."""
    code = _int_code(error.code)
    message = str(error)
    detail = f"error inside HTTP 200 (code {error.code}): {_excerpt(message)}"
    if code == 429:
        daily = _daily_quota(_error_object(error.body), error.body, message)
        if daily is not None:
            return ProviderOutcomeError("quota", daily, status=200, body=error.body)
        return _Retry(detail, 200, error.body, _retry_hint({}, error.body, message, wall_now))
    if code is not None and 500 <= code <= 599:
        return _Retry(detail, 200, error.body)
    return ProviderOutcomeError("provider_error", detail, status=200, body=error.body)


# -- the provider -----------------------------------------------------------------------------

_NOT_JSON: Final = object()

type _Result = Completion | _Retry | ProviderOutcomeError | ProviderConfigError


def _parse_json(content: bytes) -> object:
    try:
        return json.loads(content)
    except ValueError:
        return _NOT_JSON


class OpenAICompatProvider:
    """`Provider.complete` for one (resolved) route of `config/routes.json`."""

    def __init__(  # noqa: PLR0913 (route, key, overrides and test injection points)
        self,
        route: RouteConfig,
        *,
        api_key: str | None = None,
        rpm: float | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        hooks: Hooks | None = None,
        policy: RetryPolicy | None = None,
        limiter: RouteLimiter | None = None,
    ) -> None:
        if route.placeholders:
            raise ValueError(
                f"route {route.name}: unresolved placeholders {route.placeholders}; "
                "pass the route through resolve_route first"
            )
        self.route = route
        self.url = route.base_url.rstrip("/") + "/chat/completions"
        self.rpm = rpm if rpm is not None else route.rpm
        self.hooks = hooks or Hooks()
        self.policy = policy or RetryPolicy()
        self._transport = transport
        self._limiter = limiter
        self._echo = frozenset(route.echo)
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Groq's edge rejects library default user agents (Cloudflare error 1010, seen in
            # the 5 Nov probes); a plain client name passes.
            "User-Agent": USER_AGENT,
            **route.extra_headers,
        }
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    @property
    def is_openrouter(self) -> bool:
        return "openrouter.ai" in self.route.base_url

    def limiter(self) -> RouteLimiter:
        """The injected limiter, else the route's shared one for the running event loop (not
        kept on the instance, so a provider survives a second `asyncio.run`)."""
        if self._limiter is not None:
            return self._limiter
        return shared_limiter(
            self.route.name,
            concurrency=self.route.concurrency,
            rpm=self.rpm,
            tpm=self.route.tpm,
            hooks=self.hooks,
        )

    async def complete(self, request: Request) -> Completion:
        body = wire.request_body(
            request, echo=self._echo, tool_name=self.route.tool_name_in_tool_msg
        )
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        tokens = estimate_tokens(payload)
        guard = self.route.guard_tokens
        if guard is not None and tokens > guard:
            raise ProviderOutcomeError(
                "context_overflow",
                f"context_cap: estimated {tokens} prompt tokens (chars/3) > guard {guard} "
                f"(route {self.route.name}, context {self.route.max_context_tokens})",
            )
        pace_tokens = tokens
        max_tokens = self.route.params.get("max_tokens")
        if self.route.tpm_counts_max_tokens and isinstance(max_tokens, int):
            pace_tokens += max_tokens
        content = payload.encode("utf-8")
        limiter = self.limiter()
        attempts = self.policy.max_retries + 1
        last: _Retry | None = None
        for attempt in range(1, attempts + 1):
            result = await self._attempt(content, limiter, pace_tokens)
            if isinstance(result, Completion):
                return self._finish(result)
            if isinstance(result, Exception):
                raise result
            last = result
            if attempt == attempts:
                break
            delay = self._delay(attempt, result.hint_s)
            if delay is None:
                raise ProviderOutcomeError(
                    "provider_error",
                    f"{result.reason}; provider asked to wait {result.hint_s:.0f}s "
                    f"(> {self.policy.max_wait_s:.0f}s)",
                    status=result.status,
                    body=result.body,
                )
            self._report(attempt, attempts, result, delay)
            await self.hooks.sleep(delay)
        assert last is not None
        raise ProviderOutcomeError(
            "provider_error",
            f"retries exhausted after {attempts} attempts; last: {last.reason}",
            status=last.status,
            body=last.body,
        )

    async def _attempt(self, content: bytes, limiter: RouteLimiter, pace_tokens: int) -> _Result:
        async with limiter.slot(pace_tokens):
            start = self.hooks.clock()
            sent = await self._send(content)
            latency_ms = round((self.hooks.clock() - start) * 1000)
        if not isinstance(sent, httpx2.Response):
            return sent
        return self._interpret(sent, latency_ms)

    async def _send(self, content: bytes) -> httpx2.Response | _Retry | ProviderConfigError:
        try:
            return await self._post(content)
        except httpx2.TimeoutException as exc:
            return _Retry(f"timeout ({type(exc).__name__}, {self.route.timeout_s:g}s)", None)
        except httpx2.UnsupportedProtocol as exc:
            return ProviderConfigError(self.route.name, f"bad URL {self.url}: {exc}")
        except httpx2.TransportError as exc:
            return _Retry(f"connection error ({type(exc).__name__}: {exc})", None)

    def _interpret(self, response: httpx2.Response, latency_ms: int) -> _Result:
        text = response.content.decode("utf-8", errors="replace")
        parsed = _parse_json(response.content)
        status = response.status_code
        if not 200 <= status < 300:
            body = text if parsed is _NOT_JSON else parsed
            if status == 400 and (failed := failed_tool_call(body, latency_ms)) is not None:
                return failed
            error = ErrorResponse(status, body, text, response.headers)
            return classify_http_error(self.route.name, error, self.hooks.wall_clock())
        if parsed is _NOT_JSON:
            return ProviderOutcomeError(
                "provider_error",
                f"HTTP {status} with a body that is not JSON: {_excerpt(text)}",
                status=status,
                body=text,
            )
        try:
            return wire.parse_chat_completion(parsed, latency_ms=latency_ms)
        except wire.EmbeddedError as exc:
            return classify_embedded_error(exc, self.hooks.wall_clock())

    async def _post(self, content: bytes) -> httpx2.Response:
        # One client per call: no connection pool outlives an event loop, nothing to close
        # at shutdown; the TLS handshake is negligible next to a model call.
        client = httpx2.AsyncClient(
            transport=self._transport,
            timeout=httpx2.Timeout(self.route.timeout_s),
            trust_env=self._transport is None,
        )
        try:
            return await client.post(self.url, content=content, headers=self._headers)
        finally:
            if self._transport is None:  # an injected transport belongs to the caller
                await client.aclose()

    def _delay(self, attempt: int, hint_s: float | None) -> float | None:
        policy = self.policy
        backoff = min(policy.max_delay_s, policy.base_delay_s * 2.0 ** (attempt - 1))
        jittered = backoff * (0.5 + 0.5 * self.hooks.rng.random())
        if hint_s is None:
            return jittered
        if hint_s > policy.max_wait_s:
            return None
        return max(hint_s, jittered)

    def _report(self, attempt: int, attempts: int, retry: _Retry, delay: float) -> None:
        logger.warning(
            "%s: attempt %d/%d failed (%s); retrying %s in %.1fs",
            self.route.name,
            attempt,
            attempts,
            retry.reason,
            self.route.model,
            delay,
        )
        if self.hooks.on_event is not None:
            self.hooks.on_event(
                RetryEvent(
                    route=self.route.name,
                    model=self.route.model,
                    attempt=attempt,
                    max_attempts=attempts,
                    reason=retry.reason,
                    status=retry.status,
                    delay_s=delay,
                )
            )

    def _finish(self, completion: Completion) -> Completion:
        usage = completion.usage
        if self.route.free:
            usage = usage.model_copy(update={"cost_usd": 0.0, "cost_source": "free_tier"})
        elif self.is_openrouter and usage.cost_usd is not None:
            usage = usage.model_copy(update={"cost_source": "openrouter_usage"})
        return completion.model_copy(
            update={
                "usage": usage,
                "provider_served": completion.provider_served or self.route.name,
            }
        )


__all__ = [
    "ErrorResponse",
    "Hooks",
    "OpenAICompatProvider",
    "ProviderConfigError",
    "RetryEvent",
    "RetryPolicy",
    "RouteLimiter",
    "classify_embedded_error",
    "classify_http_error",
    "estimate_tokens",
    "shared_limiter",
]
