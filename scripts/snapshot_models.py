"""Snapshot OpenRouter's public model listing and derive the per-model parameter sets.

    uv run python scripts/snapshot_models.py

Writes, for the candidate models only (the full listing is ~1 MB and changes daily):
  config/models-YYYY-MM-DD.json   raw listing entries + each model's endpoints (providers)
  config/model_params.json        what the harness may send to each model (plan §2 #8)

No key is needed: /api/v1/models and /api/v1/models/<id>/endpoints are public.
"""

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

# Today's instances of the pre-registered selection rule (plan §2 #7) plus judge candidates.
GRID = [
    "anthropic/claude-sonnet-5.5",
    "anthropic/claude-haiku-5.5",
    "openai/gpt-6-luna",
    "qwen/qwen3.8-27b",
    "google/gemini-3.5-flash-lite",
]
JUDGE_CANDIDATES = [
    "openai/gpt-6.1-terra",
    "mistralai/mistral-medium-3-5",
    "deepseek/deepseek-v3.2",
    "meta-llama/llama-4-maverick",
]

# Plan §2 #8: what we would like to send; the snapshot decides what is actually allowed.
DESIRED: dict[str, dict[str, Any]] = {
    "anthropic/claude-sonnet-5.5": {"reasoning": {"effort": "low"}},
    "google/gemini-3.5-flash-lite": {"temperature": 0, "reasoning": {"effort": "low"}},
}
DEFAULT_DESIRED: dict[str, Any] = {
    "temperature": 0,
    "seed": 42,
    "reasoning": {"effort": "none"},
}
PINNED_PROVIDER = {
    "anthropic/": "anthropic",
    "openai/": "openai",
    "qwen/qwen3.8-27b": "deepinfra",
    "google/": "google-ai-studio",
}
MAX_TOKENS = 4096


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "afandem-snapshot"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _pin(model_id: str) -> str | None:
    for prefix, slug in PINNED_PROVIDER.items():
        if model_id.startswith(prefix):
            return slug
    return None


def _params_for(model_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    supported = set(entry.get("supported_parameters", []))
    desired = {**DEFAULT_DESIRED, **DESIRED.get(model_id, {})}
    sent: dict[str, Any] = {"max_tokens": MAX_TOKENS, "tool_choice": "auto"}
    dropped: list[str] = []
    for name, value in desired.items():
        if name in supported:
            sent[name] = value
        else:
            dropped.append(name)
    return {
        "params_sent": sent,
        "dropped_unsupported": sorted(dropped),
        "supports_tools": "tools" in supported,
        "reasoning_info": entry.get("reasoning"),
        "pinned_provider": _pin(model_id),
        "pricing_per_token": entry.get("pricing"),
    }


def main() -> int:
    today = datetime.now(UTC).date().isoformat()
    listing = _get(f"{BASE}/models")["data"]
    by_id = {m["id"]: m for m in listing}
    wanted = GRID + JUDGE_CANDIDATES
    snapshot: dict[str, Any] = {"taken_at": datetime.now(UTC).isoformat(), "models": {}}
    params: dict[str, Any] = {"snapshot": f"models-{today}.json", "models": {}}
    missing = []
    for model_id in wanted:
        entry = by_id.get(model_id)
        if entry is None:
            missing.append(model_id)
            continue
        try:
            endpoints = _get(f"{BASE}/models/{model_id}/endpoints").get("data")
        except OSError as exc:
            endpoints = {"error": str(exc)}
        snapshot["models"][model_id] = {"listing": entry, "endpoints": endpoints}
        if model_id in GRID:
            params["models"][model_id] = _params_for(model_id, entry)
    CONFIG.mkdir(exist_ok=True)
    (CONFIG / f"models-{today}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CONFIG / "model_params.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"listing: {len(listing)} models; saved {len(snapshot['models'])}; missing {missing}")
    for model_id, p in params["models"].items():
        print(f"  {model_id}: send {sorted(p['params_sent'])}, dropped {p['dropped_unsupported']}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
