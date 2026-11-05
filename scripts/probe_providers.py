"""Phase 0/1 raw API probes. Run once the keys you have are in .env:

    uv run --env-file .env python scripts/probe_providers.py            # every route with a key
    uv run --env-file .env python scripts/probe_providers.py groq_qwen  # one route

Routes (endpoint, model, params_sent, provider preferences, echo list) come from
config/routes.json, so the probe sends what the harness will send. Each probe sends one
English user message with one tool, then (if the model called the tool) sends the assistant
turn back exactly as received with a tool result, and saves the raw requests (without keys),
responses and rate-limit headers to tests/fixtures/providers/<route>_round{1,2}.json.

- A 400 on round 1 drops the route's `droppable` params once and retries; both calls are
  saved (`<route>_round1_rejected.json`).
- A 400 on round 2 (the verbatim echo) retries once with the harness echo (role, content,
  tool_calls plus the route's `echo` fields); both calls are saved.
- Routes whose key (or URL placeholder such as CLOUDFLARE_ACCOUNT_ID) is missing are skipped.
  The keyless local route (Ollama) runs only when OLLAMA_PROBE is set or it is named.

All routes are free except the OpenRouter ones (paid models, later). After a probe passes,
set the route's `verified` to true in config/routes.json and note the date in
docs/providers.md.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from afandem.providers.http import USER_AGENT
from afandem.providers.routes import MissingKeyError, RouteConfig, load_routes, resolve_route
from afandem.providers.wire import message_to_wire, messages_from_wire

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "providers"

SYSTEM = (
    "You are a clinic booking assistant. Today is Wednesday 2026-11-04 (Africa/Cairo). "
    "Use the tools to act. Ask when a required detail is missing."
)
USER = "Please book me an appointment this Sunday at 5 pm. My name is Mona Mahmoud."
TOOL_RESULT = {"appointment_id": "appt_0001", "status": "booked"}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a clinic appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Full name of the patient"},
                    "date": {"type": "string", "description": "ISO date, YYYY-MM-DD"},
                    "time": {"type": "string", "description": "24-hour time, HH:MM"},
                },
                "required": ["patient_name", "date", "time"],
                "additionalProperties": False,
            },
        },
    }
]
RATE_HEADER_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after", "x-request-id")


def _rate_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {
        name.lower(): value
        for name, value in headers.items()
        if name.lower().startswith(RATE_HEADER_PREFIXES)
    }


def _request(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
) -> tuple[int, Any, dict[str, str]]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.load(response), _rate_headers(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw), _rate_headers(exc.headers)
        except json.JSONDecodeError:
            return exc.code, raw, _rate_headers(exc.headers)
    except OSError as exc:
        return 0, f"network error: {exc}", {}


def _save(name: str, record: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _message(resp: Any) -> dict[str, Any] | None:
    if isinstance(resp, dict):
        choices = resp.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            return msg if isinstance(msg, dict) else None
    return None


def _body(route: RouteConfig, messages: list[dict[str, Any]], params: dict[str, Any]) -> Any:
    return {
        "model": route.model,
        "messages": messages,
        "tools": TOOLS,
        **params,
        **route.provider_prefs,
    }


def _tool_messages(route: RouteConfig, calls: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        message: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": call.get("id"),
            "content": json.dumps(TOOL_RESULT),
        }
        if route.tool_name_in_tool_msg:
            function = call.get("function")
            message["name"] = function.get("name") if isinstance(function, dict) else None
        out.append(message)
    return out


def _error_code(body: dict[str, Any]) -> object:
    """The `error.code` of an error body (a model's unparseable tool call is `tool_use_failed`
    on Groq: model output, not a rejected parameter, so parameters are not dropped for it)."""
    error = body.get("error")
    return error.get("code") if isinstance(error, dict) else None


def probe(route: RouteConfig, key: str | None) -> dict[str, Any]:
    url = f"{route.base_url}/chat/completions"
    headers = {"User-Agent": USER_AGENT, **route.extra_headers}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    params = dict(route.params)
    body = _body(route, messages, params)
    status, resp, rate = _request("POST", url, headers, body)
    result: dict[str, Any] = {"model": route.model, "round1_status": status}
    tool_use_failed = isinstance(resp, dict) and _error_code(resp) == "tool_use_failed"
    result["tool_use_failed"] = tool_use_failed
    if status == 400 and route.droppable and not tool_use_failed:
        _save(
            f"{route.name}_round1_rejected",
            {"request": body, "status": status, "response": resp, "headers": rate},
        )
        for name in route.droppable:
            params.pop(name, None)
        body = _body(route, messages, params)
        status, resp, rate = _request("POST", url, headers, body)
        result.update({"rejected_params": list(route.droppable), "round1_status": status})
    _save(
        f"{route.name}_round1",
        {"request": body, "status": status, "response": resp, "headers": rate},
    )
    result["params_sent"] = params
    result["rate_limit_headers"] = rate
    message = _message(resp)
    calls = message.get("tool_calls") if message else None
    result["tool_calls"] = len(calls) if isinstance(calls, list) else 0
    result["legacy_function_call"] = bool(message and message.get("function_call"))
    if isinstance(resp, dict):
        result["usage"] = resp.get("usage")
        result["response_model"] = resp.get("model")
        result["provider_field"] = resp.get("provider")
        choices = resp.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            result["finish_reason"] = choices[0].get("finish_reason")
    if message and isinstance(calls, list) and calls:
        echoed = dict(message)  # the assistant turn exactly as received
        tool_messages = _tool_messages(route, calls)
        body2 = dict(body)
        body2["messages"] = [*messages, echoed, *tool_messages]
        status2, resp2, rate2 = _request("POST", url, headers, body2)
        result["extra_fields_received"] = sorted(set(echoed) - {"role", "content", "tool_calls"})
        result["harness_echo"] = list(route.echo)
        if status2 == 400:
            _save(
                f"{route.name}_round2_rejected",
                {"request": body2, "status": status2, "response": resp2, "headers": rate2},
            )
            internal = messages_from_wire([message])[0]
            harness = message_to_wire(internal, echo=frozenset(route.echo))
            body2["messages"] = [*messages, harness, *tool_messages]
            status2, resp2, rate2 = _request("POST", url, headers, body2)
            result["round2_verbatim_rejected"] = True
        _save(
            f"{route.name}_round2",
            {"request": body2, "status": status2, "response": resp2, "headers": rate2},
        )
        result["round2_status"] = status2
    if "openrouter.ai" in route.base_url and isinstance(resp, dict) and resp.get("id"):
        time.sleep(3)
        lookup = f"{route.base_url}/generation?id={resp['id']}"
        g_status, g_resp, _ = _request("GET", lookup, headers)
        _save(f"{route.name}_generation_lookup", {"status": g_status, "response": g_resp})
        data = g_resp.get("data") if isinstance(g_resp, dict) else None
        result["served_provider"] = data.get("provider_name") if isinstance(data, dict) else None
    return result


def main(argv: list[str]) -> int:
    routes = load_routes()
    wanted = set(argv)
    unknown = wanted - set(routes)
    if unknown:
        print(f"unknown route(s) {sorted(unknown)}; known: {', '.join(routes)}", file=sys.stderr)
        return 2
    summary: dict[str, Any] = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for name, route in routes.items():
        if wanted and name not in wanted:
            continue
        if route.key_env is None and name not in wanted and not os.environ.get("OLLAMA_PROBE"):
            print(f"skip {name}: local route; set OLLAMA_PROBE or name it")
            continue
        try:
            resolved = resolve_route(route)
        except MissingKeyError as exc:
            print(f"skip {name}: {exc.variable} not set")
            continue
        key = os.environ.get(route.key_env) if route.key_env else None
        summary[name] = probe(resolved, key)
        print(name, json.dumps(summary[name], ensure_ascii=False))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
