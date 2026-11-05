"""Response cache (docs/harness-spec.md §6): SQLite, keyed by a hash of the internal request.

- `cache/responses.sqlite` (git-ignored): `journal_mode=WAL`, `busy_timeout=5000`, one
  connection per process behind an `asyncio.Lock`, `INSERT OR IGNORE` on the key.
- One writer process at a time: a lock file next to the database holds the writer's PID. A
  live holder makes the open fail loudly; a stale one (dead PID) is recovered. Readers
  (`readonly=True`, e.g. offline scoring) take no lock, so a run and a score may overlap.
- Key: SHA-256 of the canonical JSON of route, model, internal messages, canonical tools,
  `params_sent`, provider preferences, `CACHE_SCHEMA` and the salt. SDK and wire objects are
  never hashed, so a client-library release cannot change keys.
- Value: the full `Completion` JSON (including `raw`, signatures intact), timestamp, latency,
  `response.model` and `system_fingerprint`. A `run_calls` table lists every key a run used
  (hits included), so one run's calls can be exported as an immutable shard.
"""

import asyncio
import atexit
import contextlib
import gzip
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from afandem.providers.base import (
    Completion,
    JSONDict,
    Provider,
    Request,
    canonical_json,
    dump_message,
)

CACHE_SCHEMA: Final = 1
"""Bump to invalidate every key (a change in what the key or the stored value means)."""

LOCK_SUFFIX: Final = "-lock"
"""`responses.sqlite-lock`: matched by the `cache/*.sqlite-*` ignore rule like -wal and -shm."""
_FRESH_LOCK_S: Final = 10.0  # an unreadable lock file younger than this is being written

logger = logging.getLogger(__name__)

_SCHEMA_SQL: Final = """
CREATE TABLE IF NOT EXISTS meta (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    model TEXT NOT NULL,
    completion TEXT NOT NULL,
    created_at TEXT NOT NULL,
    latency_ms INTEGER,
    response_model TEXT,
    system_fingerprint TEXT,
    cache_schema INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS run_calls (
    run_id TEXT NOT NULL,
    key TEXT NOT NULL,
    target TEXT NOT NULL,
    ts TEXT NOT NULL,
    PRIMARY KEY (run_id, key, target)
);
CREATE INDEX IF NOT EXISTS run_calls_by_target ON run_calls (run_id, target);
"""


class CacheMissError(Exception):
    """Offline mode and the key is not in the cache."""

    def __init__(self, key: str, target: str) -> None:
        super().__init__(
            f"cache miss for key {key} (target {target}) in offline mode; import the run's "
            "shard (scripts/export_cache.py import) or run online"
        )
        self.key = key
        self.target = target


class CacheLockedError(Exception):
    """Another live process (or another open cache in this one) holds the writer lock."""


class ShardExistsError(FileExistsError):
    """A shard with different content already exists; shards are immutable."""


def cache_key(request: Request, salt: str | None = None) -> str:
    """SHA-256 over the canonical JSON of the request in the internal model."""
    target = request.target
    doc = {
        "provider": target.route,
        "model": target.model,
        "messages": [dump_message(message) for message in request.messages],
        "tools": list(request.tools),
        "params": target.params,
        "provider_prefs": target.provider_prefs,
        "cache_schema": CACHE_SCHEMA,
        "salt": salt,
    }
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by someone else
        return True
    return True


class ResponseCache:
    """The SQLite response cache. Use as a context manager, or call `close()`."""

    def __init__(self, path: Path | str, *, readonly: bool = False) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + LOCK_SUFFIX)
        self.readonly = readonly
        self._lock = asyncio.Lock()
        self._owns_lock = False
        if readonly:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, isolation_level=None)
            self._conn.execute("PRAGMA busy_timeout=5000")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_writer_lock()
        try:
            self._conn = sqlite3.connect(self.path, isolation_level=None)
            mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(f"{self.path}: could not enable WAL (got {mode})")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('cache_schema', ?)",
                (str(CACHE_SCHEMA),),
            )
        except BaseException:
            self._release_writer_lock()
            raise

    # -- writer lock -------------------------------------------------------------------

    def _acquire_writer_lock(self) -> None:
        for _ in range(3):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                holder = _read_pid(self.lock_path)
                if holder is None:
                    with contextlib.suppress(OSError):
                        age = time.time() - self.lock_path.stat().st_mtime
                        if age < _FRESH_LOCK_S:
                            raise CacheLockedError(
                                f"{self.path} is being locked by another process "
                                f"({self.lock_path} is new and empty)"
                            ) from None
                elif _pid_alive(holder):
                    where = "this process" if holder == os.getpid() else f"PID {holder}"
                    raise CacheLockedError(
                        f"{self.path} is open for writing by {where} (lock file "
                        f"{self.lock_path}); one writer at a time. If that process is not "
                        "an afandem run, delete the lock file."
                    ) from None
                logger.warning("recovering stale cache lock %s (holder %s)", self.lock_path, holder)
                with contextlib.suppress(FileNotFoundError):
                    self.lock_path.unlink()
                continue
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(f"{os.getpid()}\n")
            self._owns_lock = True
            atexit.register(self._release_writer_lock)
            return
        raise CacheLockedError(f"could not acquire {self.lock_path}")

    def _release_writer_lock(self) -> None:
        if not self._owns_lock:
            return
        self._owns_lock = False
        atexit.unregister(self._release_writer_lock)
        if _read_pid(self.lock_path) == os.getpid():
            with contextlib.suppress(FileNotFoundError):
                self.lock_path.unlink()

    def close(self) -> None:
        with contextlib.suppress(sqlite3.ProgrammingError):
            self._conn.close()
        self._release_writer_lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- synchronous access (scripts, export/import) ---------------------------------

    def pragma(self, name: str) -> object:
        if not re.fullmatch(r"[a-z_]+", name):
            raise ValueError(f"bad pragma name {name!r}")
        return self._conn.execute(f"PRAGMA {name}").fetchone()[0]

    def lookup(self, key: str) -> Completion | None:
        row = self._conn.execute(
            "SELECT completion FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return Completion.model_validate_json(row[0])

    def store(self, key: str, *, route: str, model: str, completion: Completion) -> bool:
        """Insert unless the key exists; True when a row was added."""
        if completion.finish_reason == "error":
            raise ValueError("a completion with finish_reason 'error' is never cached")
        stored = completion.model_copy(update={"cache_key": key, "cache_hit": False})
        return self.insert_row(
            key=key,
            route=route,
            model=model,
            completion=canonical_json(stored.model_dump(mode="json")),
            created_at=_now(),
            latency_ms=stored.latency_ms,
            response_model=stored.response_model,
            system_fingerprint=stored.system_fingerprint,
            schema=CACHE_SCHEMA,
        )

    def insert_row(  # noqa: PLR0913 (one column each)
        self,
        *,
        key: str,
        route: str,
        model: str,
        completion: str,
        created_at: str,
        latency_ms: int | None,
        response_model: str | None,
        system_fingerprint: str | None,
        schema: int,
    ) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO responses (key, route, model, completion, created_at, "
            "latency_ms, response_model, system_fingerprint, cache_schema) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                route,
                model,
                completion,
                created_at,
                latency_ms,
                response_model,
                system_fingerprint,
                schema,
            ),
        )
        return cursor.rowcount == 1

    def record_call(self, run_id: str, key: str, target: str, ts: str | None = None) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO run_calls (run_id, key, target, ts) VALUES (?, ?, ?, ?)",
            (run_id, key, target, ts or _now()),
        )

    def run_rows(self, run_id: str, target: str) -> list[JSONDict]:
        """Every cached response one run used for one target, as shard rows, sorted by key."""
        cursor = self._conn.execute(
            "SELECT c.key, c.ts, r.route, r.model, r.completion, r.created_at, r.latency_ms, "
            "r.response_model, r.system_fingerprint, r.cache_schema "
            "FROM run_calls c JOIN responses r ON r.key = c.key "
            "WHERE c.run_id = ? AND c.target = ? ORDER BY c.key",
            (run_id, target),
        )
        rows: list[JSONDict] = []
        for (
            key,
            ts,
            route,
            model,
            completion,
            created_at,
            latency_ms,
            response_model,
            system_fingerprint,
            schema,
        ) in cursor:
            rows.append(
                {
                    "cache_schema": schema,
                    "completion": json.loads(completion),
                    "created_at": created_at,
                    "key": key,
                    "latency_ms": latency_ms,
                    "model": model,
                    "response_model": response_model,
                    "route": route,
                    "run_id": run_id,
                    "system_fingerprint": system_fingerprint,
                    "target": target,
                    "ts": ts,
                }
            )
        return rows

    def run_targets(self, run_id: str) -> list[str]:
        """The targets a run recorded calls for, sorted."""
        cursor = self._conn.execute(
            "SELECT DISTINCT target FROM run_calls WHERE run_id = ? ORDER BY target", (run_id,)
        )
        return [str(row[0]) for row in cursor]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    # -- asynchronous access (the run), serialised by one asyncio.Lock -----------------

    async def get(self, key: str) -> Completion | None:
        async with self._lock:
            return self.lookup(key)

    async def put(self, key: str, request: Request, completion: Completion) -> bool:
        async with self._lock:
            return self.store(
                key, route=request.target.route, model=request.target.model, completion=completion
            )

    async def add_run_call(self, run_id: str, key: str, target: str) -> None:
        async with self._lock:
            self.record_call(run_id, key, target)


class CachedProvider:
    """Serves a request from the cache, else calls `inner` and stores the completion.

    A hit returns the stored completion with `cache_hit=True`; it never reaches `inner`, so a
    `BudgetedProvider` below this one is not charged. Exceptions (`ProviderOutcomeError`,
    budget exhaustion) are never stored, nor is a completion with `finish_reason == "error"`.
    With `offline=True` a miss raises `CacheMissError` instead of calling.
    """

    def __init__(
        self,
        inner: Provider,
        cache: ResponseCache,
        *,
        salt: str | None = None,
        run_id: str | None = None,
        offline: bool = False,
    ) -> None:
        self.inner = inner
        self.cache = cache
        self.salt = salt
        self.run_id = run_id
        self.offline = offline

    async def complete(self, request: Request) -> Completion:
        key = cache_key(request, self.salt)
        hit = await self.cache.get(key)
        if hit is not None:
            await self._record(key, request)
            return hit.model_copy(update={"cache_hit": True, "cache_key": key})
        if self.offline:
            raise CacheMissError(key, request.target.name)
        completion = await self.inner.complete(request)
        completion = completion.model_copy(update={"cache_hit": False, "cache_key": key})
        if completion.finish_reason != "error":
            await self.cache.put(key, request, completion)
            await self._record(key, request)
        return completion

    async def _record(self, key: str, request: Request) -> None:
        if self.run_id is not None:
            await self.cache.add_run_call(self.run_id, key, request.target.name)


# -- shards ------------------------------------------------------------------------------


def _safe(part: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._@-]+", "-", part).strip("-.")
    if not cleaned:
        raise ValueError(f"cannot build a shard file name from {part!r}")
    return cleaned


def shard_path(out_dir: Path | str, target_name: str, run_id: str) -> Path:
    return Path(out_dir) / f"{_safe(target_name)}-{_safe(run_id)}.jsonl.gz"


def shard_bytes(rows: list[JSONDict]) -> bytes:
    """Deterministic gzip of the rows: sorted keys, one per line, gzip mtime 0, no name."""
    lines = [canonical_json(row) for row in sorted(rows, key=lambda row: str(row["key"]))]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as gz:
        gz.write(payload)
    return buffer.getvalue()


def export_shard(cache: ResponseCache, run_id: str, target_name: str, out_dir: Path | str) -> Path:
    """Write `<out_dir>/<target>-<run_id>.jsonl.gz` with every response the run used.

    Shards are immutable: an existing file with the same bytes is left as it is (export is
    idempotent); one with different bytes raises `ShardExistsError`. Raises `ValueError`
    when the run recorded no calls for the target.
    """
    rows = cache.run_rows(run_id, target_name)
    if not rows:
        raise ValueError(f"no cached calls recorded for run {run_id!r} and target {target_name!r}")
    data = shard_bytes(rows)
    out = shard_path(out_dir, target_name, run_id)
    if out.exists():
        if out.read_bytes() == data:
            return out
        raise ShardExistsError(f"{out} exists with different content; shards are immutable")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    try:
        os.link(tmp, out)  # atomic, and fails if another export won the race
    except FileExistsError:
        raise ShardExistsError(f"{out} appeared during export; shards are immutable") from None
    finally:
        tmp.unlink(missing_ok=True)
    return out


def iter_shard(path: Path | str) -> Iterator[JSONDict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row: Any = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}: shard line is not an object")
                yield row


def import_shard(cache: ResponseCache, path: Path | str) -> int:
    """Load a shard into the cache (responses and the run's call list); returns the number of
    responses that were new. A shard written under another `CACHE_SCHEMA` is refused."""
    added = 0
    for row in iter_shard(path):
        if row.get("cache_schema") != CACHE_SCHEMA:
            raise ValueError(
                f"{path}: cache_schema {row.get('cache_schema')} != {CACHE_SCHEMA}; its keys "
                "can never match this version"
            )
        completion = Completion.model_validate(row["completion"])
        key = str(row["key"])
        if completion.cache_key not in (None, key):
            raise ValueError(f"{path}: row {key} carries a different cache_key")
        if cache.insert_row(  # the shard row keeps its original timestamp
            key=key,
            route=str(row["route"]),
            model=str(row["model"]),
            completion=canonical_json(row["completion"]),
            created_at=str(row["created_at"]),
            latency_ms=row.get("latency_ms"),
            response_model=row.get("response_model"),
            system_fingerprint=row.get("system_fingerprint"),
            schema=CACHE_SCHEMA,
        ):
            added += 1
        cache.record_call(str(row["run_id"]), key, str(row["target"]), str(row["ts"]))
    return added


__all__ = [
    "CACHE_SCHEMA",
    "CacheLockedError",
    "CacheMissError",
    "CachedProvider",
    "ResponseCache",
    "ShardExistsError",
    "cache_key",
    "export_shard",
    "import_shard",
    "iter_shard",
    "shard_bytes",
    "shard_path",
]
