"""Run directories: `traces.jsonl`, `index.json`, `run.json`, `tools.json` (harness-spec §7).

`traces.jsonl` is append-only, one line per (scenario, column, target, repeat) attempt, each
line flushed and `fsync`ed. `index.json` maps `scenario_id|column|target|repeat` to the latest
line of that item with its status and outcome; it is rewritten atomically (temporary file +
`os.replace`) after every item and is what `--resume` reads.

Crash safety. A line is written and synced before the index points to it, so after a crash:

- a partial last line (no trailing newline) was never indexed; opening the run truncates it;
- a complete line the index does not know yet (the crash fell between the two writes) is adopted
  into the index instead of being run again.

Either way no item is written twice. Item status: `done` (terminal: `ok`,
`blocked_by_provider`, `context_overflow`) or `error` (`provider_error`, re-run by
`--retry-errors`; `quota`, re-run by any `--resume`).

Arabic is written verbatim (`ensure_ascii=False`).
"""

import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from afandem.agent.loop import CallRow, CompletionRow, TurnRecord
from afandem.providers.base import JSONDict, Outcome
from afandem.scoring import Scores

TRACE_SCHEMA: Final = 2
TRACES_FILE: Final = "traces.jsonl"
INDEX_FILE: Final = "index.json"
RUN_FILE: Final = "run.json"
TOOLS_FILE: Final = "tools.json"

ItemStatus = Literal["done", "error"]
ERROR_OUTCOMES: Final = frozenset({"provider_error", "quota"})


class RunExistsError(Exception):
    """The run directory already holds traces and `--resume` was not given."""


class TraceCorruptError(Exception):
    """A complete line of `traces.jsonl` is not a valid record."""


class TraceRecord(BaseModel):
    """One line of `traces.jsonl` (trace_schema 2). Fields not computable yet are None."""

    model_config = ConfigDict(extra="forbid")

    trace_schema: Literal[2] = TRACE_SCHEMA
    prompt_version: str
    scorer_version: str
    normaliser_version: str | None = None
    judge_version: str | None = None
    probe_version: str | None = None
    run_id: str
    run_date: str
    started_at: str
    finished_at: str
    scenario_id: str
    scenario_sha256: str
    revision: int
    authoring_batch: str
    domain: str
    behaviour: str
    column: str
    target: str
    route: str
    model: str
    provider_served: str | None
    response_model: str | None
    system_fingerprint: str | None
    params_sent: JSONDict
    provider_prefs: JSONDict
    repeat: int
    salt: str | None
    messages: list[JSONDict]
    tool_calls: list[CallRow]
    state_initial: JSONDict
    state_final: JSONDict
    expected_state: JSONDict
    usage: list[CompletionRow]
    turns: list[TurnRecord]
    follow_up_rule: str
    follow_up_delivered: bool
    finish_reasons: list[str]
    outcome: Outcome
    outcome_detail: str | None
    flags: list[str]
    scores: Scores

    @property
    def key(self) -> str:
        return item_key(self.scenario_id, self.column, self.target, self.repeat)


def item_key(scenario_id: str, column: str, target: str, repeat: int) -> str:
    return f"{scenario_id}|{column}|{target}|{repeat}"


def item_status(outcome: str) -> ItemStatus:
    return "error" if outcome in ERROR_OUTCOMES else "done"


def dumps_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_json_atomic(path: Path, value: object) -> None:
    """Write pretty JSON next to `path`, sync it and `os.replace` it into place."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_of(record: Mapping[str, Any]) -> str:
    return item_key(
        str(record["scenario_id"]),
        str(record["column"]),
        str(record["target"]),
        int(record["repeat"]),
    )


def read_traces(run_dir: Path) -> Iterator[tuple[int, JSONDict]]:
    """(1-based line number, record) for every complete line of `traces.jsonl`."""
    path = run_dir / TRACES_FILE
    if not path.exists():
        return
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.endswith(b"\n"):
                return  # a partial last line is never a record
            try:
                yield number, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TraceCorruptError(f"{path}:{number}: {exc}") from exc


def read_index(run_dir: Path) -> dict[str, JSONDict]:
    path = run_dir / INDEX_FILE
    if not path.exists():
        return {}
    data = read_json(path)
    return dict(data.get("items", {}))


def latest_records(run_dir: Path) -> dict[str, JSONDict]:
    """The record each index entry points to, keyed by item key."""
    index = read_index(run_dir)
    wanted = {entry["line"]: key for key, entry in index.items()}
    return {wanted[number]: record for number, record in read_traces(run_dir) if number in wanted}


class RunWriter:
    """Appends trace lines and keeps `index.json` in step, one item at a time."""

    def __init__(self, run_dir: Path, *, resume: bool = False) -> None:
        self.run_dir = run_dir
        self.traces_path = run_dir / TRACES_FILE
        self.index_path = run_dir / INDEX_FILE
        run_dir.mkdir(parents=True, exist_ok=True)
        has_traces = self.traces_path.exists() and self.traces_path.stat().st_size > 0
        if has_traces and not resume:
            raise RunExistsError(f"{run_dir} already holds traces; pass --resume to continue it")
        self.index: dict[str, JSONDict] = read_index(run_dir)
        self.lines = self._recover()
        self._handle = self.traces_path.open("a", encoding="utf-8")

    def _recover(self) -> int:
        """Drop a partial last line, adopt complete unindexed lines; return the line count."""
        if not self.traces_path.exists():
            return 0
        data = self.traces_path.read_bytes()
        complete = data.rfind(b"\n") + 1
        if complete < len(data):
            with self.traces_path.open("r+b") as handle:
                handle.truncate(complete)
                handle.flush()
                os.fsync(handle.fileno())
        count = 0
        changed = False
        for number, record in read_traces(self.run_dir):
            count = number
            key = _key_of(record)
            entry = self.index.get(key)
            if entry is None or int(entry["line"]) < number:
                self.index[key] = self._entry(str(record["outcome"]), number)
                changed = True
        if changed:
            self._write_index()
        return count

    @staticmethod
    def _entry(outcome: str, line: int) -> JSONDict:
        return {"status": item_status(outcome), "outcome": outcome, "line": line}

    def _write_index(self) -> None:
        write_json_atomic(self.index_path, {"trace_schema": TRACE_SCHEMA, "items": self.index})

    def write(self, record: TraceRecord) -> int:
        """Append one record (synced), then point the index at it; returns its line number."""
        self._handle.write(dumps_line(record.model_dump(mode="json")) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.lines += 1
        self.index[record.key] = self._entry(record.outcome, self.lines)
        self._write_index()
        return self.lines

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "RunWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def write_tools(run_dir: Path, tools: Mapping[str, str]) -> None:
    """`tools.json`: each domain's canonical tool list (from `tools_canonical_json()`)."""
    write_json_atomic(
        run_dir / TOOLS_FILE, {domain: json.loads(text) for domain, text in sorted(tools.items())}
    )


def run_totals(run_dir: Path) -> JSONDict:
    """Totals over every line of `traces.jsonl` (retried items count every attempt)."""
    calls = uncached = 0
    prompt = completion = reasoning = 0
    cost = 0.0
    outcomes: dict[str, int] = {}
    lines = 0
    for _, record in read_traces(run_dir):
        lines += 1
        outcome = str(record.get("outcome"))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        for row in record.get("usage", []):
            calls += 1
            uncached += not row.get("cache_hit", False)
            prompt += row.get("prompt_tokens") or 0
            completion += row.get("completion_tokens") or 0
            reasoning += row.get("reasoning_tokens") or 0
            cost += row.get("cost_usd") or 0.0
    return {
        "lines": lines,
        "items": len(read_index(run_dir)),
        "outcomes": dict(sorted(outcomes.items())),
        "calls": calls,
        "uncached_calls": uncached,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 6),
    }


__all__ = [
    "INDEX_FILE",
    "RUN_FILE",
    "TOOLS_FILE",
    "TRACES_FILE",
    "TRACE_SCHEMA",
    "RunExistsError",
    "RunWriter",
    "TraceCorruptError",
    "TraceRecord",
    "item_key",
    "item_status",
    "latest_records",
    "read_index",
    "read_json",
    "read_traces",
    "run_totals",
    "write_json_atomic",
    "write_tools",
]
