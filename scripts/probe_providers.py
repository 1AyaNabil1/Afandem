"""Phase 0/1 raw API probes. Run once the keys you have are in .env:

    uv run --env-file .env python scripts/probe_providers.py            # every route with a key
    uv run --env-file .env python scripts/probe_providers.py groq_qwen  # one route

Each probe sends one English user message with one tool, then (if the model called the
tool) sends the assistant turn back exactly as received with a tool result, and saves the
raw requests (without keys) and responses to tests/fixtures/providers/<route>_round{1,2}.json.
If a reasoning/thinking parameter is rejected, the probe retries once without it and
records both. Probes whose key is missing are skipped. All routes are free except the
OpenRouter ones (paid models, later).

The pilot runs on the free routes (docs/free-pilot-models.md); OpenRouter is for the paid
grid once funded.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class Route:
    name: str
    key_env: str
    base_url: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)
    droppable: tuple[str, ...] = ()  # params to drop and retry if the first call is a 400
    extra_headers: dict[str, str] = field(default_factory=dict)


def _cloudflare_url() -> str:
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "<account>")
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"


ROUTES = [
    Route(
        "gemini_openai_compat",
        "GEMINI_FREE_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.5-flash-lite",
        {"temperature": 0, "reasoning_effort": "low", "tool_choice": "auto"},
        droppable=("reasoning_effort",),
    ),
    Route(
        "groq_qwen",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        "qwen/qwen3.8-27b",
        {"temperature": 0, "seed": 42, "reasoning_effort": "none", "tool_choice": "auto"},
        droppable=("reasoning_effort", "seed"),
    ),
    Route(
        "nvidia_deepseek",
        "NVIDIA_API_KEY",
        "https://integrate.api.nvidia.com/v1",
        "deepseek-ai/deepseek-v4.1-flash",
        {"temperature": 0, "tool_choice": "auto"},
    ),
    Route(
        "cloudflare_qwen",
        "CLOUDFLARE_API_TOKEN",
        _cloudflare_url(),
        "@cf/qwen/qwen3.8-27b",
        {"temperature": 0, "reasoning_effort": "low", "tool_choice": "auto"},
        droppable=("reasoning_effort",),
    ),
    Route(
        "fanar_tools",
        "FANAR_API_KEY",
        "https://api.fanar.qa/v1",
        os.environ.get("FANAR_MODEL", "Fanar-2.0-Tools"),
        {"temperature": 0, "tool_choice": "auto", "max_tokens": 1024},
    ),
    Route(
        "ollama_local",
        "OLLAMA_PROBE",
        "http://localhost:11434/v1",
        os.environ.get("OLLAMA_MODEL", "gpt-oss:20b"),
        {"temperature": 0},
    ),
    # Paid routes for the funded grid (not used by the free pilot).
    Route(
        "openrouter_haiku",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "anthropic/claude-haiku-5.5",
        {
            "reasoning": {"effort": "none"},
            "tool_choice": "auto",
            "max_tokens": 4096,
            "provider": {
                "order": ["anthropic"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
            },
        },
        extra_headers={"X-Title": "afandem-probe"},
    ),
]


def _request(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except OSError as exc:
        return 0, f"network error: {exc}"


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


def probe(route: Route, key: str) -> dict[str, Any]:
    url = f"{route.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", **route.extra_headers}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    params = dict(route.params)
    body = {"model": route.model, "messages": messages, "tools": TOOLS, **params}
    status, resp = _request("POST", url, headers, body)
    result: dict[str, Any] = {"round1_status": status}
    if status == 400 and route.droppable:
        _save(
            f"{route.name}_round1_rejected", {"request": body, "status": status, "response": resp}
        )
        for name in route.droppable:
            params.pop(name, None)
        body = {"model": route.model, "messages": messages, "tools": TOOLS, **params}
        status, resp = _request("POST", url, headers, body)
        result.update({"rejected_params": list(route.droppable), "round1_status": status})
    _save(f"{route.name}_round1", {"request": body, "status": status, "response": resp})
    message = _message(resp)
    calls = message.get("tool_calls") if message else None
    result["tool_calls"] = len(calls) if isinstance(calls, list) else 0
    result["usage"] = resp.get("usage") if isinstance(resp, dict) else None
    if message and isinstance(calls, list) and calls:
        echoed = dict(message)  # the assistant turn exactly as received
        tool_messages = [
            {"role": "tool", "tool_call_id": c.get("id"), "content": json.dumps(TOOL_RESULT)}
            for c in calls
            if isinstance(c, dict)
        ]
        body2 = dict(body)
        body2["messages"] = [*messages, echoed, *tool_messages]
        status2, resp2 = _request("POST", url, headers, body2)
        _save(f"{route.name}_round2", {"request": body2, "status": status2, "response": resp2})
        result["round2_status"] = status2
        result["extra_fields_echoed"] = sorted(set(echoed) - {"role", "content", "tool_calls"})
    if route.name == "openrouter_haiku" and isinstance(resp, dict) and resp.get("id"):
        time.sleep(3)
        g_status, g_resp = _request("GET", f"{route.base_url}/generation?id={resp['id']}", headers)
        _save("openrouter_generation_lookup", {"status": g_status, "response": g_resp})
        data = g_resp.get("data") if isinstance(g_resp, dict) else None
        result["served_provider"] = data.get("provider_name") if isinstance(data, dict) else None
    return result


def main(argv: list[str]) -> int:
    wanted = set(argv)
    summary: dict[str, Any] = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for route in ROUTES:
        if wanted and route.name not in wanted:
            continue
        key = os.environ.get(route.key_env)
        if route.name == "ollama_local" and key:
            key = "ollama"
        if not key:
            print(f"skip {route.name}: {route.key_env} not set")
            continue
        summary[route.name] = probe(route, key)
        print(route.name, json.dumps(summary[route.name], ensure_ascii=False))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
