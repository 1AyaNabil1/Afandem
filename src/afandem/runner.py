"""Run scenarios x columns x targets x repeats into a run directory (harness-spec §4, §7).

Scheduling. Each target has its own worker with `concurrency` items in flight (default 1);
targets run side by side. Within a target, items go scenario by scenario, repeat by repeat, the
six columns together, so a stop leaves whole pairs behind it.

Stops and exit codes:

- `BudgetExhaustedError` (the shared `--budget` of uncached calls is used up): nothing new is
  scheduled, the item in flight is discarded and stays non-terminal, `run.json` gets
  `stopped: "budget"`; exit code 3;
- an item whose outcome is `quota` stops its target (the rest of the run goes on); the item is
  written and re-run by the next `--resume`; exit code 4;
- `--strict-drift`: a `model_drift` flag stops its target; exit code 5.

Drift. The first `response_model` seen per target is remembered (in `run.json`, so a resume
keeps it); an episode with a completion that reports a different model gets the flag
`model_drift`. `system_fingerprint` is recorded on every call but is not a drift signal: Groq
returned a different fingerprint on consecutive calls to the same model in the 5 Nov 2026
probes (decision D18).

Repeats. The provider factory receives the repeat number; real targets salt the cache per
repeat (`repeat_salt`), so `--repeat 3` makes three uncached calls instead of one call and two
replays.

Resume. A fresh run refuses a directory that already holds traces. `--resume` skips items whose
index status is `done`; items with outcome `quota` are always re-run; `--retry-errors` also
re-runs `provider_error` items (a new line; the index points to the latest).
"""

import asyncio
import datetime as dt
import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from afandem.agent.loop import FOLLOW_UP_RULE, Episode, run_episode
from afandem.agent.prompts import PromptSet
from afandem.providers.base import BudgetExhaustedError, CallBudget, JSONDict, Provider, Target
from afandem.sandbox import DOMAINS
from afandem.scenarios import COLUMNS, LoadedScenario, Scenario
from afandem.scenarios.schema import Column
from afandem.scoring import NORMALISER_VERSION, SCORER_VERSION, Gold, prepare_gold, score_episode
from afandem.trace import (
    RUN_FILE,
    TRACE_SCHEMA,
    RunWriter,
    TraceRecord,
    item_key,
    read_json,
    run_totals,
    write_json_atomic,
    write_tools,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
MODEL_PARAMS: Final = PROJECT_ROOT / "config" / "model_params.json"

EXIT_OK: Final = 0
EXIT_BUDGET: Final = 3
EXIT_QUOTA: Final = 4
EXIT_DRIFT: Final = 5

type ProviderFactory = Callable[[Scenario, Column, int], Provider]
"""Builds the provider for one episode from (scenario, column, repeat); repeats are 1-based.
Real targets return one shared instance per repeat, the fake an episode-scoped one."""


def repeat_salt(base: str | None, repeat: int) -> str | None:
    """The cache salt of one repeat: the base salt (`--no-cache`) for repeat 1, plus
    `repeat-<k>` for later repeats, so each repeat is a fresh call."""
    if repeat == 1:
        return base
    return f"{base}|repeat-{repeat}" if base else f"repeat-{repeat}"


@dataclass(frozen=True)
class RunTarget:
    target: Target
    provider_for: ProviderFactory
    salt: str | None = None


@dataclass(frozen=True)
class RunOptions:
    run_id: str
    runs_dir: Path
    prompts: PromptSet
    columns: Sequence[Column] = COLUMNS
    repeats: int = 1
    resume: bool = False
    retry_errors: bool = False
    concurrency: int = 1
    strict_drift: bool = False
    budget: CallBudget | None = None
    model_params: Path = MODEL_PARAMS

    @property
    def run_dir(self) -> Path:
        return self.runs_dir / self.run_id


@dataclass(frozen=True)
class Item:
    loaded: LoadedScenario
    column: Column
    run_target: RunTarget
    repeat: int

    @property
    def key(self) -> str:
        return item_key(
            self.loaded.scenario.id, self.column, self.run_target.target.name, self.repeat
        )


@dataclass
class RunResult:
    run_dir: Path
    exit_code: int
    stopped: str | None
    written: int
    skipped: int
    outcomes: Counter[str] = field(default_factory=Counter)
    target_stops: dict[str, str] = field(default_factory=dict)


def plan_items(
    scenarios: Sequence[LoadedScenario],
    columns: Sequence[Column],
    targets: Sequence[RunTarget],
    repeats: int,
) -> list[Item]:
    return [
        Item(loaded, column, run_target, repeat)
        for run_target in targets
        for loaded in scenarios
        for repeat in range(1, repeats + 1)
        for column in columns
    ]


def should_run(entry: JSONDict | None, *, retry_errors: bool) -> bool:
    """Resume rule for one index entry."""
    if entry is None:
        return True
    if entry.get("outcome") == "quota":
        return True
    return entry.get("status") == "error" and retry_errors


def data_hash(scenarios: Sequence[LoadedScenario]) -> str:
    """SHA-256 over the sorted scenario SHA-256s, one per line."""
    joined = "\n".join(sorted(item.sha256 for item in scenarios))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


def git_state(root: Path = PROJECT_ROOT) -> tuple[str | None, bool | None]:
    """(HEAD sha, dirty) or (None, None) when git or the repository is unavailable."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return sha or None, bool(status.strip())


def models_snapshot(path: Path) -> tuple[str | None, str | None]:
    """(snapshot file name, its date) from `config/model_params.json`."""
    try:
        snapshot = read_json(path).get("snapshot")
    except (OSError, ValueError):
        return None, None
    if not isinstance(snapshot, str):
        return None, None
    stem = snapshot.removesuffix(".json")
    date = stem.removeprefix("models-") if stem.startswith("models-") else None
    return snapshot, date


async def _all(coroutines: Iterable[Coroutine[Any, Any, None]]) -> None:
    """Run coroutines as tasks; if one raises, cancel and await the rest, then re-raise."""
    tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _target_meta(run_target: RunTarget) -> JSONDict:
    target = run_target.target
    return {
        "name": target.name,
        "route": target.route,
        "model": target.model,
        "params_sent": target.params,
        "provider_prefs": target.provider_prefs,
        "salt": run_target.salt,
    }


class Runner:
    def __init__(
        self,
        scenarios: Sequence[LoadedScenario],
        targets: Sequence[RunTarget],
        options: RunOptions,
    ) -> None:
        if options.repeats < 1 or options.concurrency < 1:
            raise ValueError("repeats and concurrency must be >= 1")
        names = [rt.target.name for rt in targets]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate target names: {names}")
        self.scenarios = list(scenarios)
        self.targets = list(targets)
        self.options = options
        self.run_dir = options.run_dir
        self.prompts: dict[str, str] = {
            item.scenario.id: options.prompts.render(item.scenario) for item in self.scenarios
        }
        self.gold: dict[str, Gold] = {
            item.scenario.id: prepare_gold(item.scenario) for item in self.scenarios
        }
        self.stop_budget = False
        self.target_stops: dict[str, str] = {}
        self.baseline: dict[str, dict[str, str]] = {}
        self.outcomes: Counter[str] = Counter()
        self.written = 0
        self.meta: JSONDict = {}

    # ------------------------------------------------------------ run.json

    def _start_meta(self) -> None:
        path = self.run_dir / RUN_FILE
        previous: JSONDict = read_json(path) if path.exists() else {}
        sha, dirty = git_state()
        snapshot, snapshot_date = models_snapshot(self.options.model_params)
        now = _now()
        targets = {t["name"]: t for t in previous.get("targets", [])}
        targets.update({rt.target.name: _target_meta(rt) for rt in self.targets})
        self.baseline = {k: dict(v) for k, v in previous.get("drift_baseline", {}).items()}
        self.meta = {
            "run_id": self.options.run_id,
            "trace_schema": TRACE_SCHEMA,
            "started_at": previous.get("started_at", now),
            "resumed_at": [*previous.get("resumed_at", []), *([now] if previous else [])],
            "finished_at": None,
            "git_sha": sha,
            "git_dirty": dirty,
            "data_hash": data_hash(self.scenarios),
            "scenarios": len(self.scenarios),
            "columns": list(self.options.columns),
            "repeats": self.options.repeats,
            "models_snapshot": snapshot,
            "models_snapshot_date": snapshot_date,
            "targets": [targets[name] for name in sorted(targets)],
            "prompt_version": self.options.prompts.version,
            "scorer_version": SCORER_VERSION,
            "normaliser_version": NORMALISER_VERSION,
            "follow_up_rule": FOLLOW_UP_RULE,
            "budget": None if self.options.budget is None else self.options.budget.limit,
            "stopped": None,
            "target_stops": {},
            "drift_baseline": self.baseline,
            "totals": previous.get("totals"),
        }
        write_json_atomic(path, self.meta)
        domains = {item.scenario.domain for item in self.scenarios}
        write_tools(self.run_dir, {d: DOMAINS[d][1].tools_canonical_json() for d in domains})

    def _finish_meta(self, stopped: str | None) -> None:
        self.meta.update(
            {
                "finished_at": _now(),
                "stopped": stopped,
                "target_stops": dict(sorted(self.target_stops.items())),
                "drift_baseline": self.baseline,
                "totals": run_totals(self.run_dir),
            }
        )
        if self.options.budget is not None:
            self.meta["budget_used"] = self.options.budget.used
        write_json_atomic(self.run_dir / RUN_FILE, self.meta)

    # ------------------------------------------------------------ items

    def _drift(self, target: str, episode: Episode) -> bool:
        seen = self.baseline.setdefault(target, {})
        drifted = False
        for row in episode.usage:
            value = row.response_model
            if value is None:
                continue
            first = seen.setdefault("response_model", value)
            drifted = drifted or value != first
        return drifted

    def _record(self, item: Item, episode: Episode, started: str, salt: str | None) -> TraceRecord:
        scenario = item.loaded.scenario
        target = item.run_target.target
        gold = self.gold[scenario.id]
        scores = score_episode(scenario, episode, gold=gold)
        return TraceRecord(
            prompt_version=self.options.prompts.version,
            scorer_version=SCORER_VERSION,
            normaliser_version=NORMALISER_VERSION,
            run_id=self.options.run_id,
            run_date=started[:10],
            started_at=started,
            finished_at=_now(),
            scenario_id=scenario.id,
            scenario_sha256=item.loaded.sha256,
            revision=scenario.revision,
            authoring_batch=scenario.authoring_batch,
            domain=scenario.domain,
            behaviour=scenario.behaviour,
            column=item.column,
            target=target.name,
            route=target.route,
            model=target.model,
            provider_served=episode.first_seen("provider_served"),
            response_model=episode.first_seen("response_model"),
            system_fingerprint=episode.first_seen("system_fingerprint"),
            params_sent=target.params,
            provider_prefs=target.provider_prefs,
            repeat=item.repeat,
            salt=salt,
            messages=[m.model_dump(mode="json") for m in episode.messages],
            tool_calls=episode.tool_calls,
            state_initial=episode.state_initial,
            state_final=episode.state_final,
            expected_state=gold.expected,
            usage=episode.usage,
            turns=episode.turns,
            follow_up_rule=episode.follow_up_rule,
            follow_up_delivered=episode.follow_up_delivered,
            finish_reasons=episode.finish_reasons,
            outcome=episode.outcome,
            outcome_detail=episode.outcome_detail,
            flags=episode.flags,
            scores=scores,
        )

    async def _one(self, item: Item, writer: RunWriter) -> None:
        name = item.run_target.target.name
        if self.stop_budget or name in self.target_stops:
            return
        scenario = item.loaded.scenario
        started = _now()
        try:
            episode = await run_episode(
                scenario,
                item.column,
                item.run_target.provider_for(scenario, item.column, item.repeat),
                target=item.run_target.target,
                system_prompt=self.prompts[scenario.id],
            )
        except BudgetExhaustedError:
            self.stop_budget = True
            return
        if self._drift(name, episode):
            episode.add_flag("model_drift")
            if self.options.strict_drift:
                self.target_stops.setdefault(name, "drift")
        if episode.outcome == "quota":
            self.target_stops.setdefault(name, "quota")
        salt = repeat_salt(item.run_target.salt, item.repeat)
        writer.write(self._record(item, episode, started, salt))
        self.written += 1
        self.outcomes[episode.outcome] += 1

    async def _target(self, items: list[Item], writer: RunWriter) -> None:
        gate = asyncio.Semaphore(self.options.concurrency)

        async def guarded(item: Item) -> None:
            async with gate:
                await self._one(item, writer)

        await _all(guarded(item) for item in items)

    async def run(self) -> RunResult:
        writer = RunWriter(self.run_dir, resume=self.options.resume)
        stopped: str | None = "interrupted"
        try:
            self._start_meta()
            planned = plan_items(
                self.scenarios, self.options.columns, self.targets, self.options.repeats
            )
            todo = [
                item
                for item in planned
                if should_run(writer.index.get(item.key), retry_errors=self.options.retry_errors)
            ]
            by_target: dict[str, list[Item]] = {}
            for item in todo:
                by_target.setdefault(item.run_target.target.name, []).append(item)
            await _all(self._target(items, writer) for items in by_target.values())
            stopped = self._stop_reason()
        finally:
            writer.close()
            self._finish_meta(stopped)
        return RunResult(
            run_dir=self.run_dir,
            exit_code=self._exit_code(),
            stopped=stopped,
            written=self.written,
            skipped=len(planned) - len(todo),
            outcomes=self.outcomes,
            target_stops=dict(self.target_stops),
        )

    def _stop_reason(self) -> str | None:
        if self.stop_budget:
            return "budget"
        reasons = set(self.target_stops.values())
        for reason in ("quota", "drift"):
            if reason in reasons:
                return reason
        return None

    def _exit_code(self) -> int:
        if self.stop_budget:
            return EXIT_BUDGET
        reasons = set(self.target_stops.values())
        if "quota" in reasons:
            return EXIT_QUOTA
        if "drift" in reasons:
            return EXIT_DRIFT
        return EXIT_OK


async def run(
    scenarios: Sequence[LoadedScenario], targets: Sequence[RunTarget], options: RunOptions
) -> RunResult:
    """Run every planned item not already terminal in the run directory."""
    return await Runner(scenarios, targets, options).run()


def default_run_id(*, fake: bool, now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.UTC)
    return moment.strftime("%Y%m%dT%H%M%SZ") + ("-fake" if fake else "")


def count_items(
    scenarios: Sequence[LoadedScenario],
    columns: Sequence[Column],
    targets: Sequence[RunTarget],
    repeats: int,
) -> int:
    return len(scenarios) * len(columns) * len(targets) * repeats


def parameter_table(targets: Sequence[RunTarget]) -> list[dict[str, Any]]:
    return [_target_meta(rt) for rt in targets]


__all__ = [
    "EXIT_BUDGET",
    "EXIT_DRIFT",
    "EXIT_OK",
    "EXIT_QUOTA",
    "Item",
    "ProviderFactory",
    "RunOptions",
    "RunResult",
    "RunTarget",
    "Runner",
    "count_items",
    "data_hash",
    "default_run_id",
    "git_state",
    "models_snapshot",
    "parameter_table",
    "plan_items",
    "repeat_salt",
    "run",
    "should_run",
]
