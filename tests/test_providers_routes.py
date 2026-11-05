import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from afandem.providers.base import BudgetedProvider, CallBudget, Request, UserMsg
from afandem.providers.cache import CachedProvider, ResponseCache
from afandem.providers.http import OpenAICompatProvider
from afandem.providers.routes import (
    DEFAULT_ROUTES_PATH,
    MissingKeyError,
    RouteConfig,
    build_provider,
    load_routes,
    resolve_route,
    route_names,
    target_for,
)

MODEL_PARAMS = DEFAULT_ROUTES_PATH.parent / "model_params.json"
FREE = [
    "gemini_free",
    "groq_qwen",
    "groq_gptoss",
    "nvidia_deepseek",
    "cloudflare_qwen",
    "fanar_tools",
]
EXPECTED = [
    *FREE,
    "ollama_local",
    "ollama_cloud",
    "openrouter_haiku",
    "openrouter_sonnet",
    "openrouter_luna",
    "openrouter_qwen",
    "openrouter_gemini",
]
OPENROUTER_MODELS = {
    "openrouter_haiku": "anthropic/claude-haiku-5.5",
    "openrouter_sonnet": "anthropic/claude-sonnet-5.5",
    "openrouter_luna": "openai/gpt-6-luna",
    "openrouter_qwen": "qwen/qwen3.8-27b",
    "openrouter_gemini": "google/gemini-3.5-flash-lite",
}
FULL_ENV = {
    "GEMINI_FREE_API_KEY": "k1",
    "GROQ_API_KEY": "k2",
    "NVIDIA_API_KEY": "k3",
    "CLOUDFLARE_API_TOKEN": "k4",
    "CLOUDFLARE_ACCOUNT_ID": "acct123",
    "FANAR_API_KEY": "k5",
    "OPENROUTER_API_KEY": "k6",
}


@pytest.fixture(scope="module")
def routes() -> dict[str, RouteConfig]:
    return load_routes()


def test_every_route_is_defined_and_unverified(routes: dict[str, RouteConfig]) -> None:
    assert list(routes) == EXPECTED
    assert route_names() == EXPECTED
    verified = {name for name, route in routes.items() if route.verified}
    assert verified == {
        "gemini_free",
        "groq_qwen",
        "groq_gptoss",
        "ollama_cloud",
    }  # live probes, 5 Nov 2026
    labels = [route.label for route in routes.values()]
    assert len(set(labels)) == len(labels)
    assert {name for name, route in routes.items() if route.free} == {
        *FREE,
        "ollama_local",
        "ollama_cloud",
    }


def test_free_route_parameters(routes: dict[str, RouteConfig]) -> None:
    for name, route in routes.items():
        params = route.params
        assert params["max_tokens"] == (1024 if name == "fanar_tools" else 4096), name
        assert "parallel_tool_calls" not in params, name
        if name == "ollama_local":
            assert "tool_choice" not in params
        else:
            assert params["tool_choice"] == "auto", name
        if "temperature" in params:
            assert params["temperature"] == 0, name
    assert routes["gemini_free"].params["reasoning_effort"] == "low"
    assert routes["groq_qwen"].params["reasoning_effort"] == "none"
    assert routes["cloudflare_qwen"].params["reasoning_effort"] in ("low", "none")
    assert routes["ollama_local"].params["reasoning_effort"] == "low"
    assert routes["ollama_local"].key_env is None
    assert routes["groq_qwen"].tpm == 8000


def test_fanar_whitelist_and_context(routes: dict[str, RouteConfig]) -> None:
    fanar = routes["fanar_tools"]
    assert set(fanar.params) <= {"temperature", "max_tokens", "tool_choice"}
    assert fanar.params["tool_choice"] in ("auto", "none")
    assert fanar.tool_name_in_tool_msg is True
    assert fanar.max_context_tokens == 8192
    assert fanar.guard_tokens is not None and fanar.guard_tokens <= 8192 - 1024
    assert fanar.provider_prefs == {}
    assert sum(route.tool_name_in_tool_msg for route in routes.values()) == 1


def test_openrouter_routes_follow_the_snapshot(routes: dict[str, RouteConfig]) -> None:
    snapshot = json.loads(MODEL_PARAMS.read_text(encoding="utf-8"))["models"]
    for name, model in OPENROUTER_MODELS.items():
        route = routes[name]
        entry = snapshot[model]
        assert route.model == model
        assert route.base_url == "https://openrouter.ai/api/v1"
        assert route.key_env == "OPENROUTER_API_KEY"
        assert route.params == entry["params_sent"], name
        assert not set(entry["dropped_unsupported"]) & set(route.params), name
        prefs = route.provider_prefs["provider"]
        assert prefs["order"] == [entry["pinned_provider"]]
        assert prefs["allow_fallbacks"] is False
        assert prefs["require_parameters"] is True
        assert prefs["data_collection"] == "deny"
        assert ("quantizations" in prefs) == (name == "openrouter_qwen")
        assert route.echo == ("reasoning_details",)
        assert not route.free
    assert routes["openrouter_qwen"].provider_prefs["provider"]["quantizations"] == ["bf16"]


def test_target_for(routes: dict[str, RouteConfig]) -> None:
    target = target_for(routes["groq_qwen"])
    assert target.name == "qwen3.8-27b@groq"
    assert target.route == "groq_qwen"
    assert target.model == "qwen/qwen3.8-27b"
    assert target.params == routes["groq_qwen"].params
    sonnet = target_for(routes["openrouter_sonnet"])
    assert sonnet.provider_prefs == routes["openrouter_sonnet"].provider_prefs


def test_resolve_fills_placeholders_and_checks_variables(routes: dict[str, RouteConfig]) -> None:
    cloudflare = routes["cloudflare_qwen"]
    assert cloudflare.placeholders == ("CLOUDFLARE_ACCOUNT_ID",)
    resolved = resolve_route(cloudflare, FULL_ENV)
    assert resolved.base_url == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/v1"
    assert resolved.placeholders == ()
    with pytest.raises(MissingKeyError) as info:
        resolve_route(cloudflare, {"CLOUDFLARE_API_TOKEN": "t"})
    assert info.value.variable == "CLOUDFLARE_ACCOUNT_ID"
    with pytest.raises(MissingKeyError) as info:
        resolve_route(routes["groq_qwen"], {"GROQ_API_KEY": ""})  # .env.example leaves it empty
    assert info.value.variable == "GROQ_API_KEY"
    assert resolve_route(routes["ollama_local"], {}).base_url == "http://localhost:11434/v1"


def test_model_override_moves_the_label(routes: dict[str, RouteConfig]) -> None:
    ollama = resolve_route(routes["ollama_local"], {"OLLAMA_MODEL": "gemma4:26b-a4b-it-qat"})
    assert ollama.model == "gemma4:26b-a4b-it-qat"
    assert ollama.label == "gemma4-26b-a4b-it-qat@ollama"
    same = resolve_route(
        routes["fanar_tools"], {"FANAR_API_KEY": "k", "FANAR_MODEL": "Fanar-2.0-Tools"}
    )
    assert same.label == "fanar-2.0-tools@fanar"


def test_missing_key_error_before_any_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network client built")

    monkeypatch.setattr(httpx2, "AsyncClient", no_network)
    assert issubclass(MissingKeyError, Exception)
    for name in EXPECTED:
        if name == "ollama_local":
            continue
        with pytest.raises(MissingKeyError):
            build_provider(name, budget=CallBudget(1), env={})


def test_build_provider_uses_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(MissingKeyError):
        build_provider("groq_qwen", budget=CallBudget(1))
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    target, _ = build_provider("groq_qwen", budget=CallBudget(1))
    assert target.name == "qwen3.8-27b@groq"


def test_unknown_route() -> None:
    with pytest.raises(ValueError, match="unknown route"):
        build_provider("nope", budget=CallBudget(1), env=FULL_ENV)


def test_build_provider_composition(tmp_path: Path) -> None:
    budget = CallBudget(3)
    target, provider = build_provider("cloudflare_qwen", budget=budget, env=FULL_ENV, rpm=12)
    assert target.name == "qwen3.8-27b@cloudflare"
    assert isinstance(provider, BudgetedProvider)
    assert provider.budget is budget
    http = provider.inner
    assert isinstance(http, OpenAICompatProvider)
    assert (
        http.url == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/v1/chat/completions"
    )
    assert http.rpm == 12
    with ResponseCache(tmp_path / "responses.sqlite") as cache:
        _, cached = build_provider(
            "groq_qwen", budget=budget, cache=cache, salt="s1", run_id="r1", env=FULL_ENV
        )
        assert isinstance(cached, CachedProvider)
        assert (cached.cache, cached.salt, cached.run_id, cached.offline) == (
            cache,
            "s1",
            "r1",
            False,
        )
        assert isinstance(cached.inner, BudgetedProvider)
        assert isinstance(cached.inner.inner, OpenAICompatProvider)


async def test_cache_hits_through_build_provider_do_not_consume_budget(tmp_path: Path) -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        body = {  # hand-written OpenAI-shaped response
            "id": "r",
            "model": "qwen/qwen3.8-27b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "[fixture reply]"},
                    "finish_reason": "stop",
                }
            ],
        }
        return httpx2.Response(200, json=body)

    budget = CallBudget(1)
    with ResponseCache(tmp_path / "responses.sqlite") as cache:
        target, provider = build_provider("groq_qwen", budget=budget, cache=cache, env=FULL_ENV)
        assert isinstance(provider, CachedProvider)
        assert isinstance(provider.inner, BudgetedProvider)
        http = provider.inner.inner
        assert isinstance(http, OpenAICompatProvider)
        http._transport = httpx2.MockTransport(handler)  # test-only injection after composition
        request = Request(
            target=target, messages=(UserMsg(content="[fixture user text]"),), tools=()
        )
        first = await provider.complete(request)
        second = await provider.complete(request)  # budget is used up: only a hit can answer
    assert len(calls) == 1
    assert budget.used == 1
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert calls[0].headers["authorization"] == "Bearer k2"


def _route_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "x",
        "label": "m@x",
        "base_url": "https://x.test/v1",
        "key_env": None,
        "model": "m",
        "params": {"max_tokens": 10},
        "free": True,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        {"label": "no-host"},
        {"params": {"model": "other"}},
        {"provider_prefs": {"messages": []}},
        {"droppable": ["seed"]},
        {"surprise": True},
        {"concurrency": 0},
    ],
)
def test_route_config_validation(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RouteConfig.model_validate(_route_dict(**overrides))


def test_load_routes_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "routes.json"
    path.write_text(
        json.dumps(
            {"version": 1, "checked": "2026-11-05", "routes": [_route_dict(), _route_dict()]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_routes(path)
