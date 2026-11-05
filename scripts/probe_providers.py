"""Phase 0 raw API probes (plan §12 #9). Run once the keys exist:

    uv run --env-file .env python scripts/probe_providers.py

Each probe sends one user message with one tool and saves the raw request (without the
key) and the raw response to tests/fixtures/providers/<name>.json, so the harness is built
against real response shapes. Probes whose key is missing are skipped. Cost: a few cents.

What the probes answer:
  or_haiku_basic            tool call shape, `usage.cost`, served provider (via /generation)
  or_haiku_temperature      does `temperature` + `require_parameters: true` fail (expected 503)?
  or_sonnet_low             Sonnet 5.5 at effort "low": reasoning tokens per call
  or_gemini_round1/round2   do Gemini 3 thought signatures survive OpenRouter when
                            `reasoning_details` is echoed back? (decides plan §2 #17)
  gemini_native_round1/2    the same through Google's own API (fallback path)
  fanar_tools               Fanar's tool-calling response shape and model id
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
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
TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "patient_name": {"type": "string", "description": "Full name of the patient"},
        "date": {"type": "string", "description": "ISO date, YYYY-MM-DD"},
        "time": {"type": "string", "description": "24-hour time, HH:MM"},
    },
    "required": ["patient_name", "date", "time"],
    "additionalProperties": False,
}
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a clinic appointment.",
            "parameters": TOOL_SCHEMA,
        },
    }
]
OR_URL = "https://openrouter.ai/api/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
FANAR_URL = "https://api.fanar.qa/v1"


def _post(url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    data = json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def _save(name: str, request: dict[str, Any], status: int, response: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    record = {"probe": name, "request": request, "status": status, "response": response}
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _or_body(model: str, extra: dict[str, Any], provider: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
        "max_tokens": 4096,
        "provider": {
            "order": [provider],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        },
        **extra,
    }


def probe_openrouter(key: str, summary: dict[str, Any]) -> None:
    auth = {"Authorization": f"Bearer {key}", "X-Title": "afandem-probe"}
    url = f"{OR_URL}/chat/completions"

    body = _or_body("anthropic/claude-haiku-5.5", {"reasoning": {"effort": "none"}}, "anthropic")
    status, resp = _post(url, body, auth)
    _save("or_haiku_basic", body, status, resp)
    summary["or_haiku_basic"] = {"status": status, "usage": _dig(resp, "usage")}
    gen_id = _dig(resp, "id")
    if isinstance(gen_id, str):
        time.sleep(3)
        g_status, g_resp = _get(f"{OR_URL}/generation?id={gen_id}", auth)
        _save("or_generation_lookup", {"id": gen_id}, g_status, g_resp)
        summary["served_provider"] = _dig(g_resp, "data", "provider_name")

    body = _or_body("anthropic/claude-haiku-5.5", {"temperature": 0}, "anthropic")
    status, resp = _post(url, body, auth)
    _save("or_haiku_temperature", body, status, resp)
    summary["or_haiku_temperature"] = {"status": status, "expected": 503}

    body = _or_body("anthropic/claude-sonnet-5.5", {"reasoning": {"effort": "low"}}, "anthropic")
    status, resp = _post(url, body, auth)
    _save("or_sonnet_low", body, status, resp)
    summary["or_sonnet_low"] = {"status": status, "usage": _dig(resp, "usage")}

    model = "google/gemini-3.5-flash-lite"
    body = _or_body(model, {"temperature": 0, "reasoning": {"effort": "low"}}, "google-ai-studio")
    status, resp = _post(url, body, auth)
    _save("or_gemini_round1", body, status, resp)
    message = _dig(resp, "choices", 0, "message")
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    summary["or_gemini_round1"] = {"status": status, "tool_calls": bool(calls)}
    if isinstance(message, dict) and calls:
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
        assistant["tool_calls"] = calls
        if message.get("reasoning_details") is not None:
            assistant["reasoning_details"] = message["reasoning_details"]
        tool_messages = [
            {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(TOOL_RESULT)}
            for call in calls
        ]
        body2 = dict(body)
        body2["messages"] = [*body["messages"], assistant, *tool_messages]
        status2, resp2 = _post(url, body2, auth)
        _save("or_gemini_round2", body2, status2, resp2)
        summary["or_gemini_round2"] = {
            "status": status2,
            "echoed_reasoning_details": "reasoning_details" in assistant,
            "signature_survives": status2 == 200,
        }


def probe_gemini_native(key: str, summary: dict[str, Any]) -> None:
    url = f"{GEMINI_URL}/gemini-3.5-flash-lite:generateContent"
    headers = {"x-goog-api-key": key}
    declaration = {
        "name": "book_appointment",
        "description": "Book a clinic appointment.",
        "parametersJsonSchema": TOOL_SCHEMA,
    }
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": USER}]}],
        "tools": [{"functionDeclarations": [declaration]}],
        "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingLevel": "low"}},
    }
    status, resp = _post(url, body, headers)
    _save("gemini_native_round1", body, status, resp)
    content = _dig(resp, "candidates", 0, "content")
    parts = content.get("parts", []) if isinstance(content, dict) else []
    calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
    has_sig = any(isinstance(p, dict) and "thoughtSignature" in p for p in parts)
    summary["gemini_native_round1"] = {
        "status": status,
        "function_calls": len(calls),
        "thought_signature_present": has_sig,
    }
    if calls and isinstance(content, dict):
        responses = [
            {"functionResponse": {"name": c["name"], "response": TOOL_RESULT}} for c in calls
        ]
        body2 = dict(body)
        body2["contents"] = [*body["contents"], content, {"role": "user", "parts": responses}]
        status2, resp2 = _post(url, body2, headers)
        _save("gemini_native_round2", body2, status2, resp2)
        summary["gemini_native_round2"] = {"status": status2}


def probe_fanar(key: str, summary: dict[str, Any]) -> None:
    auth = {"Authorization": f"Bearer {key}"}
    m_status, m_resp = _get(f"{FANAR_URL}/models", auth)
    _save("fanar_models", {}, m_status, m_resp)
    body: dict[str, Any] = {
        "model": os.environ.get("FANAR_MODEL", "Fanar-2.0-Tools"),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 1024,
    }
    status, resp = _post(f"{FANAR_URL}/chat/completions", body, auth)
    _save("fanar_tools", body, status, resp)
    summary["fanar_tools"] = {"status": status, "models_status": m_status}


def _dig(obj: Any, *path: str | int) -> Any:
    for step in path:
        if isinstance(step, int) and isinstance(obj, list) and len(obj) > step:
            obj = obj[step]
        elif isinstance(step, str) and isinstance(obj, dict):
            obj = obj.get(step)
        else:
            return None
    return obj


def main() -> int:
    summary: dict[str, Any] = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    probes = [
        ("OPENROUTER_API_KEY", probe_openrouter),
        ("GEMINI_FREE_API_KEY", probe_gemini_native),
        ("FANAR_API_KEY", probe_fanar),
    ]
    for variable, probe in probes:
        key = os.environ.get(variable)
        if not key:
            print(f"skip: {variable} not set")
            continue
        probe(key, summary)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
