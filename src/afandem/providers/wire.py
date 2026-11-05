"""OpenAI-compatible chat-completions converter: internal messages <-> wire JSON.

Every pilot route (Gemini's OpenAI-compatible endpoint, Groq, NVIDIA build, Cloudflare Workers
AI, Fanar, Ollama) and OpenRouter speak this shape, so one converter covers them. Pure
functions, no I/O: the HTTP provider and the fake model both go through them, so the converter
is exercised without keys.

Passthrough rule: an assistant message that came from a provider is sent back from its `wire`
copy, not rebuilt. `role`, `content` and `tool_calls` are always echoed (each tool call dict
verbatim, so Gemini's `extra_content.google.thought_signature` survives); any other field is
echoed only when the route lists it in `echo` (e.g. OpenRouter's `reasoning_details`), because
some servers reject fields they do not accept as input.
"""

import copy
import json
from collections.abc import Iterable, Mapping
from typing import Any, Final

from afandem.providers.base import (
    AssistantMsg,
    Completion,
    FinishReason,
    JSONDict,
    Message,
    Request,
    SystemMsg,
    ToolCall,
    ToolMsg,
    Usage,
    UserMsg,
)

ALWAYS_ECHOED: Final = ("role", "content", "tool_calls")

_FINISH: Final[Mapping[str, FinishReason]] = {
    "stop": "stop",
    "end_turn": "stop",
    "eos": "stop",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",  # legacy (Fanar)
    "tool_use": "tool_calls",
    "length": "length",
    "max_tokens": "length",
    "content_filter": "content_filter",
    "safety": "content_filter",
    "error": "error",
}


class EmbeddedError(Exception):
    """An error inside an HTTP 200 body (`error` key or no usable `choices`)."""

    def __init__(self, message: str, *, code: int | str | None, body: object) -> None:
        super().__init__(message)
        self.code = code
        self.body = body


def tool_to_wire(tool: Mapping[str, Any]) -> JSONDict:
    """`{name, description, parameters}` -> the OpenAI `tools[]` entry."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": copy.deepcopy(tool["parameters"]),
        },
    }


def _arguments_to_wire(arguments: str | Mapping[str, Any]) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def _built_tool_calls(calls: Iterable[ToolCall]) -> list[JSONDict]:
    return [
        {
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": _arguments_to_wire(call.arguments)},
        }
        for call in calls
    ]


def assistant_to_wire(message: AssistantMsg, *, echo: frozenset[str] = frozenset()) -> JSONDict:
    wire = message.wire
    if wire is None:
        out: JSONDict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            out["tool_calls"] = _built_tool_calls(message.tool_calls)
        return out
    out = {"role": "assistant", "content": copy.deepcopy(wire.get("content"))}
    if message.tool_calls:
        received = wire.get("tool_calls")
        if isinstance(received, list) and len(received) == len(message.tool_calls):
            out["tool_calls"] = copy.deepcopy(received)
        else:  # legacy `function_call`, or a shape we normalised: rebuild in the modern form
            out["tool_calls"] = _built_tool_calls(message.tool_calls)
    for key in sorted(echo):
        if key not in ALWAYS_ECHOED and key in wire:
            out[key] = copy.deepcopy(wire[key])
    return out


def message_to_wire(
    message: Message, *, echo: frozenset[str] = frozenset(), tool_name: bool = False
) -> JSONDict:
    """One internal message as a chat-completions message.

    `tool_name` adds `name` to tool results (Fanar accepts it; strict servers may not).
    """
    match message:
        case SystemMsg() | UserMsg():
            return {"role": message.role, "content": message.content}
        case AssistantMsg():
            return assistant_to_wire(message, echo=echo)
        case ToolMsg():
            out: JSONDict = {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }
            if tool_name:
                out["name"] = message.name
            return out


def request_body(
    request: Request, *, echo: frozenset[str] = frozenset(), tool_name: bool = False
) -> JSONDict:
    """The full JSON body for `POST /chat/completions`.

    Order: model, messages, tools, then `params_sent`, then provider preferences. `tools` is
    sent on every request, including follow-ups.
    """
    body: JSONDict = {
        "model": request.target.model,
        "messages": [message_to_wire(m, echo=echo, tool_name=tool_name) for m in request.messages],
    }
    if request.tools:
        body["tools"] = [tool_to_wire(tool) for tool in request.tools]
    for key, value in request.target.params.items():
        body[key] = copy.deepcopy(value)
    for key, value in request.target.provider_prefs.items():
        body[key] = copy.deepcopy(value)
    return body


def messages_from_wire(messages: Iterable[Mapping[str, Any]]) -> list[Message]:
    """Read wire messages back into the internal model (used by the fake model and tests).

    Assistant messages keep their wire copy, so `messages_to_wire(messages_from_wire(x))`
    round-trips.
    """
    out: list[Message] = []
    for raw in messages:
        role = raw.get("role")
        if role == "system":
            out.append(SystemMsg(content=str(raw.get("content") or "")))
        elif role == "user":
            out.append(UserMsg(content=str(raw.get("content") or "")))
        elif role == "assistant":
            out.append(_assistant_from_wire(raw))
        elif role == "tool":
            out.append(
                ToolMsg(
                    tool_call_id=str(raw.get("tool_call_id") or ""),
                    name=str(raw.get("name") or ""),
                    content=str(raw.get("content") or ""),
                )
            )
        else:
            raise ValueError(f"unknown message role {role!r}")
    return out


def _content_text(content: object) -> str | None:
    """`content` as text: a string, None, or a list of `{type: text, text}` parts joined."""
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        ]
        return "".join(parts)
    return str(content)


def _tool_calls_from_wire(message: Mapping[str, Any]) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    received = message.get("tool_calls")
    if isinstance(received, list):
        for index, item in enumerate(received):
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            function = function if isinstance(function, dict) else {}
            arguments = function.get("arguments")
            calls.append(
                ToolCall(
                    id=str(item.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, str | dict) else "",
                )
            )
    legacy = message.get("function_call")
    if not calls and isinstance(legacy, dict):
        arguments = legacy.get("arguments")
        calls.append(
            ToolCall(
                id="call_0",
                name=str(legacy.get("name") or ""),
                arguments=arguments if isinstance(arguments, str | dict) else "",
            )
        )
    return tuple(calls)


def _assistant_from_wire(message: Mapping[str, Any]) -> AssistantMsg:
    return AssistantMsg(
        content=_content_text(message.get("content")),
        tool_calls=_tool_calls_from_wire(message),
        wire=copy.deepcopy(dict(message)),
    )


def normalise_finish(raw: object, *, has_tool_calls: bool) -> FinishReason:
    """Map a provider's finish reason onto the five normalised values.

    A missing or unknown value is read from the message: tool calls -> `tool_calls`, else
    `stop`; the raw value is kept on the completion for audit.
    """
    if isinstance(raw, str):
        mapped = _FINISH.get(raw.lower())
        if mapped is not None:
            return mapped
    return "tool_calls" if has_tool_calls else "stop"


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def usage_from_wire(body: Mapping[str, Any]) -> Usage:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return Usage()
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    cost = usage.get("cost")
    cost_usd = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else None
    return Usage(
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        completion_tokens=_int_or_none(usage.get("completion_tokens")),
        reasoning_tokens=_int_or_none(reasoning),
        cost_usd=cost_usd,
        cost_source="provider_usage" if cost_usd is not None else None,
    )


def parse_chat_completion(body: object, *, latency_ms: int | None = None) -> Completion:
    """Parse a `/chat/completions` response body (HTTP 200) into a `Completion`.

    Raises `EmbeddedError` for an `error` object or empty `choices` inside a 200: the HTTP
    layer decides whether that is retryable from `code`.
    """
    if not isinstance(body, dict):
        raise EmbeddedError("response body is not a JSON object", code=None, body=body)
    error = body.get("error")
    if error:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise EmbeddedError(str(message), code=code, body=body)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise EmbeddedError("no choices in response", code=None, body=body)
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise EmbeddedError("choice has no message", code=None, body=body)
    choice_error = choice.get("error")
    if choice_error:
        code = choice_error.get("code") if isinstance(choice_error, dict) else None
        raise EmbeddedError(f"choice error: {choice_error}", code=code, body=body)
    assistant = _assistant_from_wire(message)
    raw_finish = choice.get("finish_reason")
    return Completion(
        assistant=assistant,
        finish_reason=normalise_finish(raw_finish, has_tool_calls=bool(assistant.tool_calls)),
        finish_reason_raw=raw_finish if isinstance(raw_finish, str) else None,
        usage=usage_from_wire(body),
        response_id=body.get("id") if isinstance(body.get("id"), str) else None,
        response_model=body.get("model") if isinstance(body.get("model"), str) else None,
        system_fingerprint=(
            body.get("system_fingerprint")
            if isinstance(body.get("system_fingerprint"), str)
            else None
        ),
        provider_served=body.get("provider") if isinstance(body.get("provider"), str) else None,
        latency_ms=latency_ms,
        raw=copy.deepcopy(body),
    )


__all__ = [
    "ALWAYS_ECHOED",
    "EmbeddedError",
    "assistant_to_wire",
    "message_to_wire",
    "messages_from_wire",
    "normalise_finish",
    "parse_chat_completion",
    "request_body",
    "tool_to_wire",
    "usage_from_wire",
]
