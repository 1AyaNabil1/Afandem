import asyncio
import gzip
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from afandem.providers.base import (
    AssistantMsg,
    BudgetedProvider,
    CallBudget,
    Completion,
    ProviderOutcomeError,
    Request,
    SystemMsg,
    Target,
    ToolCall,
    ToolMsg,
    Usage,
    UserMsg,
)
from afandem.providers.cache import (
    CACHE_SCHEMA,
    CachedProvider,
    CacheLockedError,
    CacheMissError,
    ResponseCache,
    ShardExistsError,
    cache_key,
    export_shard,
    import_shard,
    iter_shard,
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
TOOL_REORDERED = {
    "parameters": {
        "additionalProperties": False,
        "required": ["slot"],
        "properties": {"slot": {"type": "string"}},
        "type": "object",
    },
    "description": "[fixture tool description]",
    "name": "fixture_tool",
}
WIRE = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "fixture_tool", "arguments": '{"slot":"a"}'},
            "extra_content": {"google": {"thought_signature": "c2ln"}},
        }
    ],
}


def _target(**overrides: Any) -> Target:
    fields: dict[str, Any] = {
        "name": "model@route",
        "route": "route",
        "model": "vendor/model",
        "params": {"temperature": 0, "max_tokens": 64, "reasoning": {"effort": "none"}},
        "provider_prefs": {"provider": {"order": ["x"], "allow_fallbacks": False}},
    }
    fields.update(overrides)
    return Target(**fields)


def _request(target: Target | None = None, text: str = "[fixture user text]") -> Request:
    assistant = AssistantMsg(
        content=None,
        tool_calls=(ToolCall(id="c1", name="fixture_tool", arguments='{"slot":"a"}'),),
        wire=WIRE,
    )
    return Request(
        target=target or _target(),
        messages=(
            SystemMsg(content="[fixture system text]"),
            UserMsg(content=text),
            assistant,
            ToolMsg(tool_call_id="c1", name="fixture_tool", content='{"status":"ok"}'),
        ),
        tools=(TOOL,),
    )


def _completion(text: str = "[fixture reply]", finish: str = "stop") -> Completion:
    raw = {
        "id": "resp-1",
        "model": "vendor/model-001",
        "system_fingerprint": "fp_1",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    return Completion.model_validate(
        {
            "assistant": {"content": text, "wire": {"role": "assistant", "content": text}},
            "finish_reason": finish,
            "usage": Usage(
                prompt_tokens=10, completion_tokens=2, cost_usd=0.0, cost_source="free_tier"
            ),
            "response_id": "resp-1",
            "response_model": "vendor/model-001",
            "system_fingerprint": "fp_1",
            "provider_served": "route",
            "latency_ms": 321,
            "raw": raw,
        }
    )


class Inner:
    """A provider that counts calls; can be told to fail or to answer with an error finish."""

    def __init__(self, *, finish: str = "stop", fail: bool = False) -> None:
        self.calls = 0
        self.finish = finish
        self.fail = fail

    async def complete(self, request: Request) -> Completion:
        self.calls += 1
        if self.fail:
            raise ProviderOutcomeError("provider_error", "[fixture] retries exhausted", status=503)
        return _completion(f"[fixture reply {self.calls}]", self.finish)


@pytest.fixture
def cache(tmp_path: Path) -> Any:
    with ResponseCache(tmp_path / "cache" / "responses.sqlite") as opened:
        yield opened


# -- the key -----------------------------------------------------------------------------------


def test_key_is_stable_across_dict_ordering() -> None:
    first = _request()
    reordered_target = _target(
        params={"reasoning": {"effort": "none"}, "max_tokens": 64, "temperature": 0},
        provider_prefs={"provider": {"allow_fallbacks": False, "order": ["x"]}},
    )
    wire = {"tool_calls": WIRE["tool_calls"], "content": None, "role": "assistant"}
    second = Request(
        target=reordered_target,
        messages=(
            *first.messages[:2],
            first.messages[2].model_copy(update={"wire": wire}),
            first.messages[3],
        ),
        tools=(TOOL_REORDERED,),
    )
    assert cache_key(first) == cache_key(second)
    assert cache_key(first, "s") == cache_key(second, "s")


def test_key_golden_value() -> None:
    """Pinned: a change here re-keys (and re-bills) every cached call. Bump CACHE_SCHEMA."""
    assert CACHE_SCHEMA == 1
    assert cache_key(_request()) == GOLDEN_KEY


@pytest.mark.parametrize(
    "changed",
    [
        _request(_target(model="vendor/other")),
        _request(_target(route="other_route")),
        _request(
            _target(params={"temperature": 0, "max_tokens": 65, "reasoning": {"effort": "none"}})
        ),
        _request(_target(provider_prefs={})),
        _request(text="[fixture user text 2]"),
        Request(target=_target(), messages=_request().messages, tools=()),
    ],
)
def test_key_changes_with_what_is_sent(changed: Request) -> None:
    assert cache_key(changed) != cache_key(_request())


def test_key_ignores_the_display_label_and_uses_the_salt() -> None:
    assert cache_key(_request(_target(name="renamed@route"))) == cache_key(_request())
    assert cache_key(_request(), "repeat-1") != cache_key(_request())
    assert cache_key(_request(), "repeat-1") != cache_key(_request(), "repeat-2")


# -- hit and miss ------------------------------------------------------------------------------


async def test_miss_then_hit(cache: ResponseCache) -> None:
    inner = Inner()
    provider = CachedProvider(inner, cache, run_id="run-1")
    first = await provider.complete(_request())
    second = await provider.complete(_request())
    assert inner.calls == 1
    key = cache_key(_request())
    assert (first.cache_hit, first.cache_key) == (False, key)
    assert (second.cache_hit, second.cache_key) == (True, key)
    assert second.assistant == first.assistant
    assert second.raw == first.raw and second.raw is not None
    assert second.latency_ms == 321
    assert second.usage == first.usage
    assert cache.count() == 1


async def test_salt_separates_entries(cache: ResponseCache) -> None:
    inner = Inner()
    await CachedProvider(inner, cache).complete(_request())
    salted = CachedProvider(inner, cache, salt="repeat-1")
    await salted.complete(_request())
    await salted.complete(_request())
    assert inner.calls == 2
    assert cache.count() == 2


async def test_budget_is_not_consumed_on_hits(cache: ResponseCache) -> None:
    budget = CallBudget(1)
    inner = Inner()
    provider = CachedProvider(BudgetedProvider(inner, budget), cache)
    for _ in range(3):
        await provider.complete(_request())
    assert budget.used == 1 and inner.calls == 1


async def test_offline_miss_names_the_key(cache: ResponseCache) -> None:
    offline = CachedProvider(Inner(), cache, offline=True)
    with pytest.raises(CacheMissError) as info:
        await offline.complete(_request())
    key = cache_key(_request())
    assert info.value.key == key
    assert key in str(info.value)
    await CachedProvider(Inner(), cache).complete(_request())
    hit = await offline.complete(_request())
    assert hit.cache_hit


async def test_failures_and_error_finishes_are_never_stored(cache: ResponseCache) -> None:
    failing = Inner(fail=True)
    provider = CachedProvider(failing, cache, run_id="r")
    for _ in range(2):
        with pytest.raises(ProviderOutcomeError):
            await provider.complete(_request())
    assert failing.calls == 2
    erroring = Inner(finish="error")
    provider = CachedProvider(erroring, cache, run_id="r")
    result = await provider.complete(_request())
    await provider.complete(_request())
    assert result.finish_reason == "error"
    assert erroring.calls == 2
    assert cache.count() == 0
    assert cache.run_rows("r", "model@route") == []
    with pytest.raises(ValueError, match="never cached"):
        cache.store("k", route="r", model="m", completion=_completion(finish="error"))


async def test_concurrent_misses_are_serialised(cache: ResponseCache) -> None:
    provider = CachedProvider(Inner(), cache, run_id="r")
    requests = [_request(text=f"[fixture user text {i}]") for i in range(20)]
    await asyncio.gather(*(provider.complete(request) for request in requests))
    assert cache.count() == 20
    assert len(cache.run_rows("r", "model@route")) == 20


def test_sqlite_settings(cache: ResponseCache) -> None:
    assert cache.pragma("journal_mode") == "wal"
    assert cache.pragma("busy_timeout") == 5000


# -- run calls and shards ----------------------------------------------------------------------


async def _fill(
    cache: ResponseCache, run_id: str, count: int, target: Target | None = None
) -> None:
    provider = CachedProvider(Inner(), cache, run_id=run_id)
    for index in range(count):
        await provider.complete(_request(target, text=f"[fixture user text {index}]"))


async def test_run_calls_include_hits(cache: ResponseCache) -> None:
    await _fill(cache, "run-a", 2)
    await _fill(cache, "run-b", 3)  # the first two are hits for run-b
    assert len(cache.run_rows("run-a", "model@route")) == 2
    assert len(cache.run_rows("run-b", "model@route")) == 3
    assert cache.run_rows("run-b", "other@route") == []
    assert cache.count() == 3


async def test_export_is_deterministic_and_immutable(cache: ResponseCache, tmp_path: Path) -> None:
    await _fill(cache, "run-1", 3)
    await _fill(cache, "run-1", 2, _target(name="other@route2", route="route2"))
    first = export_shard(cache, "run-1", "model@route", tmp_path / "a")
    second = export_shard(cache, "run-1", "model@route", tmp_path / "b")
    assert first.name == "model@route-run-1.jsonl.gz"
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes()[4:8] == b"\x00\x00\x00\x00"  # gzip mtime 0
    lines = gzip.decompress(first.read_bytes()).decode().splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 3
    assert [row["key"] for row in rows] == sorted(row["key"] for row in rows)
    assert all(list(row) == sorted(row) for row in rows)
    assert {row["target"] for row in rows} == {"model@route"}
    assert rows[0]["completion"]["raw"]["system_fingerprint"] == "fp_1"
    assert rows[0]["cache_schema"] == CACHE_SCHEMA
    # same content again: left as it is
    assert export_shard(cache, "run-1", "model@route", tmp_path / "a") == first
    # different content: refused, file untouched
    before = first.read_bytes()
    await _fill(cache, "run-1", 4)
    with pytest.raises(ShardExistsError):
        export_shard(cache, "run-1", "model@route", tmp_path / "a")
    assert first.read_bytes() == before
    assert not [p for p in (tmp_path / "a").iterdir() if p.name.endswith(".tmp")]


def test_export_of_an_empty_run_is_refused(cache: ResponseCache, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no cached calls"):
        export_shard(cache, "nothing", "model@route", tmp_path)


async def test_import_round_trip(cache: ResponseCache, tmp_path: Path) -> None:
    await _fill(cache, "run-1", 3)
    shard = export_shard(cache, "run-1", "model@route", tmp_path / "shards")
    with ResponseCache(tmp_path / "other" / "responses.sqlite") as fresh:
        assert import_shard(fresh, shard) == 3
        assert import_shard(fresh, shard) == 0  # INSERT OR IGNORE
        offline = CachedProvider(Inner(), fresh, offline=True)
        hit = await offline.complete(_request(text="[fixture user text 1]"))
        assert hit.cache_hit and hit.assistant.content == "[fixture reply 2]"
        again = export_shard(fresh, "run-1", "model@route", tmp_path / "again")
    assert again.read_bytes() == shard.read_bytes()


def test_import_refuses_another_schema(cache: ResponseCache, tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl.gz"
    row = {"cache_schema": CACHE_SCHEMA + 1, "key": "k", "completion": {}}
    path.write_bytes(gzip.compress((json.dumps(row) + "\n").encode()))
    with pytest.raises(ValueError, match="cache_schema"):
        import_shard(cache, path)
    assert list(iter_shard(path)) == [row]


# -- the single-writer lock ----------------------------------------------------------------------


def test_second_writer_in_this_process_fails(tmp_path: Path) -> None:
    path = tmp_path / "responses.sqlite"
    with ResponseCache(path) as first:
        assert first.lock_path.name == "responses.sqlite-lock"
        assert first.lock_path.read_text().strip() == str(os.getpid())
        with pytest.raises(CacheLockedError, match="this process"):
            ResponseCache(path)
        with ResponseCache(path, readonly=True) as reader:  # readers take no lock
            assert reader.count() == 0
    assert not first.lock_path.exists()
    ResponseCache(path).close()  # released on close


def test_live_foreign_holder_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "responses.sqlite"
    lock = path.with_name("responses.sqlite-lock")
    lock.write_text(f"{os.getppid()}\n")
    with pytest.raises(CacheLockedError, match=f"PID {os.getppid()}"):
        ResponseCache(path)
    assert lock.read_text().strip() == str(os.getppid())


def test_stale_lock_is_recovered(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    finished = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        check=True,
        capture_output=True,
        text=True,
    )
    dead_pid = int(finished.stdout.strip())
    path = tmp_path / "responses.sqlite"
    lock = path.with_name("responses.sqlite-lock")
    lock.write_text(f"{dead_pid}\n")
    with (
        caplog.at_level(logging.WARNING, logger="afandem.providers.cache"),
        ResponseCache(path) as cache,
    ):
        assert cache.lock_path.read_text().strip() == str(os.getpid())
    assert any("stale" in record.getMessage() for record in caplog.records)


def test_old_empty_lock_is_recovered_but_a_fresh_one_is_not(tmp_path: Path) -> None:
    path = tmp_path / "responses.sqlite"
    lock = path.with_name("responses.sqlite-lock")
    lock.write_text("")
    with pytest.raises(CacheLockedError, match="new and empty"):
        ResponseCache(path)
    os.utime(lock, (1, 1))
    ResponseCache(path).close()


# A pinned SHA-256 cache key (not a credential).
GOLDEN_KEY = "fc3b23f0048b6a72110b32bb44f96b4e8d27146cddcd19cf399b3f06ed77c392"  # gitleaks:allow
