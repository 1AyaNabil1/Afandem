import json
from collections.abc import Mapping
from typing import Any

import pytest

from afandem.providers.base import (
    AssistantMsg,
    BudgetedProvider,
    BudgetExhaustedError,
    CallBudget,
    Completion,
    Request,
    SystemMsg,
    Target,
    ToolCall,
    ToolMsg,
    UserMsg,
    canonical_json,
    dump_message,
)
from afandem.providers.wire import (
    EmbeddedError,
    message_to_wire,
    messages_from_wire,
    normalise_finish,
    parse_chat_completion,
    request_body,
)

TARGET = Target(
    name="m@route",
    route="route",
    model="vendor/model",
    params={"temperature": 0, "tool_choice": "auto"},
    provider_prefs={"provider": {"order": ["x"]}},
)
TOOL = {
    "name": "book",
    "description": "Book.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _body(message: Mapping[str, object], finish: str | None = "stop") -> dict[str, object]:
    return {
        "id": "gen-1",
        "model": "vendor/model-2026",
        "system_fingerprint": "fp_1",
        "provider": "SomeHost",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 2},
            "cost": 0.0001,
        },
    }


def test_request_body_order_and_contents() -> None:
    request = Request(
        target=TARGET,
        messages=(SystemMsg(content="s"), UserMsg(content="مرحبا")),
        tools=(TOOL,),
    )
    body = request_body(request)
    assert list(body) == ["model", "messages", "tools", "temperature", "tool_choice", "provider"]
    assert body["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "مرحبا"},
    ]
    assert body["tools"][0] == {"type": "function", "function": TOOL}


def test_thought_signature_survives_round_trip() -> None:
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "book", "arguments": '{"a": 1}'},
        "extra_content": {"google": {"thought_signature": "SIG=="}},
    }
    message = {"role": "assistant", "content": None, "tool_calls": [call], "reasoning": "hm"}
    completion = parse_chat_completion(_body(message, "tool_calls"))
    assert completion.finish_reason == "tool_calls"
    assert completion.assistant.tool_calls == (
        ToolCall(id="c1", name="book", arguments='{"a": 1}'),
    )
    echoed = message_to_wire(completion.assistant)
    assert echoed == {"role": "assistant", "content": None, "tool_calls": [call]}
    assert "reasoning" not in echoed  # not listed in echo
    assert message_to_wire(completion.assistant, echo=frozenset({"reasoning"}))["reasoning"] == "hm"


def test_parse_usage_and_metadata() -> None:
    completion = parse_chat_completion(_body({"role": "assistant", "content": "ok"}), latency_ms=7)
    assert completion.assistant.content == "ok"
    assert completion.usage.prompt_tokens == 10
    assert completion.usage.reasoning_tokens == 2
    assert completion.usage.cost_usd == pytest.approx(0.0001)
    assert completion.response_model == "vendor/model-2026"
    assert completion.system_fingerprint == "fp_1"
    assert completion.provider_served == "SomeHost"
    assert completion.latency_ms == 7
    assert completion.raw is not None and completion.raw["id"] == "gen-1"


def test_legacy_function_call_is_rebuilt_as_tool_calls() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "function_call": {"name": "book", "arguments": "{}"},
    }
    completion = parse_chat_completion(_body(message, "function_call"))
    assert completion.finish_reason == "tool_calls"
    wire = message_to_wire(completion.assistant)
    assert wire["tool_calls"][0]["function"] == {"name": "book", "arguments": "{}"}
    assert "function_call" not in wire


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"error": {"code": 429, "message": "slow down"}}, 429),
        ({"choices": []}, None),
        ([], None),
        ({"choices": [{"message": {"role": "assistant"}, "error": {"code": 502}}]}, 502),
    ],
)
def test_errors_inside_200(body: object, code: object) -> None:
    with pytest.raises(EmbeddedError) as info:
        parse_chat_completion(body)
    assert info.value.code == code


@pytest.mark.parametrize(
    ("raw", "has_calls", "expected"),
    [
        ("stop", False, "stop"),
        ("STOP", True, "stop"),
        ("tool_calls", True, "tool_calls"),
        ("length", True, "length"),
        ("content_filter", False, "content_filter"),
        (None, True, "tool_calls"),
        (None, False, "stop"),
        ("weird", False, "stop"),
    ],
)
def test_normalise_finish(raw: object, has_calls: bool, expected: str) -> None:
    assert normalise_finish(raw, has_tool_calls=has_calls) == expected


def test_messages_round_trip_and_tool_name_flag() -> None:
    wire: list[dict[str, Any]] = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "b", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c", "content": "{}", "name": "b"},
    ]
    internal = messages_from_wire(wire)
    assert [message_to_wire(m, tool_name=True) for m in internal] == wire
    assert "name" not in message_to_wire(internal[3])


def test_locally_built_assistant_message() -> None:
    message = AssistantMsg(
        content=None, tool_calls=(ToolCall(id="c", name="b", arguments={"x": "٣"}),)
    )
    wire = message_to_wire(message)
    assert json.loads(wire["tool_calls"][0]["function"]["arguments"]) == {"x": "٣"}


def test_canonical_json_is_stable_and_unescaped() -> None:
    a = dump_message(ToolMsg(tool_call_id="c", name="b", content="منى"))
    assert canonical_json(a) == canonical_json(dict(reversed(list(a.items()))))
    assert "منى" in canonical_json(a)


async def test_budget_counts_calls_reaching_the_provider() -> None:
    class Echo:
        async def complete(self, request: Request) -> Completion:
            return Completion(assistant=AssistantMsg(content="x"), finish_reason="stop")

    budget = CallBudget(2)
    provider = BudgetedProvider(Echo(), budget)
    request = Request(target=TARGET, messages=(UserMsg(content="u"),), tools=())
    await provider.complete(request)
    await provider.complete(request)
    assert budget.remaining == 0
    with pytest.raises(BudgetExhaustedError):
        await provider.complete(request)
