"""Routes: how one model is reached (endpoint, key variable, `params_sent`, limits).

`config/routes.json` is the single source; the probe script and the HTTP provider both read
it. A route's `base_url` may contain `{ENV_VAR}` placeholders (Cloudflare's account id), filled
from the environment by `resolve_route`. `verified` stays false until the probe confirms the
route accepts its parameters.

`build_provider` is the one entry point the runner uses; it composes, outermost first,

    CachedProvider(cache, salt, run_id) -> BudgetedProvider(budget) -> OpenAICompatProvider

so a cache hit never consumes budget, and raises `MissingKeyError` before any network call
when a variable the route needs is unset.
"""

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from afandem.providers.base import BudgetedProvider, CallBudget, JSONDict, Provider, Target
from afandem.providers.cache import CachedProvider, ResponseCache

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_ROUTES_PATH: Final = REPO_ROOT / "config" / "routes.json"

_PLACEHOLDER: Final = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


class MissingKeyError(Exception):
    """A variable the route needs (API key or URL placeholder) is unset or empty."""

    def __init__(self, route: str, variable: str) -> None:
        super().__init__(
            f"route {route!r} needs {variable}, which is unset or empty; add it to .env "
            "(see .env.example) and run with `uv run --env-file .env ...`"
        )
        self.route = route
        self.variable = variable


class RouteConfig(BaseModel):
    """One route from `config/routes.json`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    label: str
    """`Target.name`: short, used in run directories and tables (`qwen3.8-27b@groq`)."""
    base_url: str
    """Without the trailing `/chat/completions`; may contain `{ENV_VAR}` placeholders."""
    key_env: str | None
    """Variable holding the bearer key; None for keyless local servers (Ollama)."""
    model: str
    model_env: str | None = None
    """Optional variable that overrides `model` (FANAR_MODEL, OLLAMA_MODEL)."""
    params: JSONDict = {}
    """`params_sent`: every body key besides model, messages and tools."""
    provider_prefs: JSONDict = {}
    """Extra top-level body keys that steer routing (OpenRouter's `provider` object)."""
    echo: tuple[str, ...] = ()
    """Assistant-message fields echoed back besides role, content and tool_calls."""
    tool_name_in_tool_msg: bool = False
    """Send `name` on tool-result messages (Fanar)."""
    extra_headers: dict[str, str] = {}
    rpm: float | None = Field(default=None, gt=0)
    """Requests per minute: the minimum interval between request starts is 60/rpm."""
    tpm: int | None = Field(default=None, gt=0)
    """Tokens per minute, paced from the chars/3 estimate of each request body."""
    tpm_counts_max_tokens: bool = False
    """Add `max_tokens` to each request's estimate for the tpm pacer."""
    concurrency: int = Field(default=1, ge=1)
    timeout_s: float = Field(default=60.0, gt=0)
    max_context_tokens: int | None = Field(default=None, gt=0)
    context_guard_tokens: int | None = Field(default=None, gt=0)
    """Estimated prompt tokens above which a call is refused locally (`context_cap`).
    Defaults to max_context_tokens - max_tokens when only max_context_tokens is set."""
    free: bool
    verified: bool = False
    droppable: tuple[str, ...] = ()
    """Probe only: params dropped (once) when the first probe call is a 400."""
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> Self:
        if "@" not in self.label:
            raise ValueError(f"route {self.name}: label must look like model@host")
        reserved = {"model", "messages", "tools"} & (set(self.params) | set(self.provider_prefs))
        if reserved:
            raise ValueError(f"route {self.name}: params may not set {sorted(reserved)}")
        unknown = set(self.droppable) - set(self.params)
        if unknown:
            raise ValueError(f"route {self.name}: droppable names unknown params {unknown}")
        return self

    @property
    def guard_tokens(self) -> int | None:
        """The prompt-size guard threshold, or None when the route has no context cap."""
        if self.context_guard_tokens is not None:
            return self.context_guard_tokens
        if self.max_context_tokens is None:
            return None
        max_tokens = self.params.get("max_tokens")
        reserve = max_tokens if isinstance(max_tokens, int) else 0
        return max(1, self.max_context_tokens - reserve)

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(_PLACEHOLDER.findall(self.base_url))


class _RoutesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    checked: str
    sources: str = ""
    routes: list[RouteConfig]


def load_routes(path: Path | str | None = None) -> dict[str, RouteConfig]:
    """Every route in `config/routes.json` (or `path`), keyed by name, in file order."""
    source = Path(path) if path is not None else DEFAULT_ROUTES_PATH
    data: Any = json.loads(source.read_text(encoding="utf-8"))
    parsed = _RoutesFile.model_validate(data)
    routes: dict[str, RouteConfig] = {}
    for route in parsed.routes:
        if route.name in routes:
            raise ValueError(f"{source}: duplicate route {route.name!r}")
        routes[route.name] = route
    return routes


def route_names(path: Path | str | None = None) -> list[str]:
    """Route names in file order (for CLI help)."""
    return list(load_routes(path))


def _label_for(model: str, label: str) -> str:
    host = label.split("@", 1)[1]
    slug = re.sub(r"[^a-z0-9.]+", "-", model.rsplit("/", 1)[-1].lower()).strip("-")
    return f"{slug}@{host}"


def _value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value if value else None


def resolve_route(route: RouteConfig, env: Mapping[str, str] | None = None) -> RouteConfig:
    """The route with `{ENV_VAR}` placeholders filled and the model override applied.

    Raises `MissingKeyError` when the key variable or a placeholder variable is unset or
    empty. When `model_env` overrides the model, the label follows the model.
    """
    env = os.environ if env is None else env
    if route.key_env is not None and _value(env, route.key_env) is None:
        raise MissingKeyError(route.name, route.key_env)
    base_url = route.base_url
    for variable in route.placeholders:
        value = _value(env, variable)
        if value is None:
            raise MissingKeyError(route.name, variable)
        base_url = base_url.replace("{" + variable + "}", value)
    update: dict[str, Any] = {"base_url": base_url.rstrip("/")}
    override = _value(env, route.model_env) if route.model_env else None
    if override is not None and override != route.model:
        update["model"] = override
        update["label"] = _label_for(override, route.label)
    return route.model_copy(update=update)


def target_for(route: RouteConfig) -> Target:
    """The `Target` for a (resolved) route: what one column of results is about."""
    return Target(
        name=route.label,
        route=route.name,
        model=route.model,
        params=dict(route.params),
        provider_prefs=dict(route.provider_prefs),
    )


def build_provider(  # noqa: PLR0913 (signature fixed by the runner contract)
    name: str,
    *,
    budget: CallBudget,
    cache: ResponseCache | None = None,
    salt: str | None = None,
    run_id: str | None = None,
    rpm: float | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[Target, Provider]:
    """The target and the composed provider for route `name`.

    `CachedProvider` (only when `cache` is given) wraps `BudgetedProvider` wraps the HTTP
    provider, so cache hits never consume budget. `rpm` overrides the route's pacing. Raises
    `MissingKeyError` before any network call when a needed variable is unset, and
    `ValueError` for an unknown route.
    """
    # http.py imports RouteConfig from this module, so this import cannot be at the top.
    from afandem.providers.http import OpenAICompatProvider  # noqa: PLC0415

    routes = load_routes()
    if name not in routes:
        raise ValueError(f"unknown route {name!r}; known routes: {', '.join(routes)}")
    env = os.environ if env is None else env
    route = resolve_route(routes[name], env)
    api_key = _value(env, route.key_env) if route.key_env else None
    provider: Provider = OpenAICompatProvider(route, api_key=api_key, rpm=rpm)
    provider = BudgetedProvider(provider, budget)
    if cache is not None:
        provider = CachedProvider(provider, cache, salt=salt, run_id=run_id)
    return target_for(route), provider


__all__ = [
    "DEFAULT_ROUTES_PATH",
    "MissingKeyError",
    "RouteConfig",
    "build_provider",
    "load_routes",
    "resolve_route",
    "route_names",
    "target_for",
]
