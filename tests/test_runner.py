"""The runner: budget stop and resume after a truncated trace, retries, quota, drift, run.json."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from afandem.agent.prompts import PromptSet
from afandem.providers.base import (
    BudgetedProvider,
    CallBudget,
    Completion,
    Provider,
    Request,
)
from afandem.providers.fake import FAKE_TARGET, FakeModel, Override, fake_factory
from afandem.runner import (
    EXIT_BUDGET,
    EXIT_DRIFT,
    EXIT_OK,
    EXIT_QUOTA,
    Runner,
    RunOptions,
    RunResult,
    RunTarget,
    data_hash,
    models_snapshot,
    plan_items,
    run,
    should_run,
)
from afandem.scenarios import COLUMNS, LoadedScenario, Scenario, load_scenarios
from afandem.scenarios.schema import Column
from afandem.trace import (
    INDEX_FILE,
    RUN_FILE,
    TRACES_FILE,
    RunExistsError,
    read_index,
    read_traces,
)

SMOKE = Path(__file__).parent / "fixtures" / "smoke"
LOADED = load_scenarios(SMOKE)
TOTAL = len(LOADED) * len(COLUMNS)


def fake_target(
    overrides: Mapping[str, Override] | None = None, budget: CallBudget | None = None
) -> RunTarget:
    def wrap(provider: Provider) -> Provider:
        return BudgetedProvider(provider, budget) if budget is not None else provider

    return RunTarget(FAKE_TARGET, fake_factory(overrides, wrap=wrap))


def options(tmp_path: Path, **changes: Any) -> RunOptions:
    base: dict[str, Any] = {
        "run_id": "r1",
        "runs_dir": tmp_path,
        "prompts": PromptSet.stub(),
    }
    base.update(changes)
    return RunOptions(**base)


async def go(
    tmp_path: Path,
    targets: list[RunTarget] | None = None,
    scenarios: list[LoadedScenario] | None = None,
    **changes: Any,
) -> RunResult:
    return await run(
        LOADED if scenarios is None else scenarios,
        targets or [fake_target()],
        options(tmp_path, **changes),
    )


def keys_in_traces(run_dir: Path) -> list[str]:
    return [
        f"{r['scenario_id']}|{r['column']}|{r['target']}|{r['repeat']}"
        for _, r in read_traces(run_dir)
    ]


async def test_full_fake_run(tmp_path: Path) -> None:
    result = await go(tmp_path)
    assert result.exit_code == EXIT_OK and result.stopped is None
    assert result.written == TOTAL and result.outcomes == {"ok": TOTAL}
    run_dir = tmp_path / "r1"
    assert len(read_index(run_dir)) == TOTAL
    records = [r for _, r in read_traces(run_dir)]
    assert all(r["scores"]["task_success"] is True for r in records)
    assert all(r["trace_schema"] == 2 and r["prompt_version"] == "stub" for r in records)
    assert {r["params_sent"]["max_tokens"] for r in records} == {4096}
    meta = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["run_id"] == "r1" and meta["stopped"] is None
    assert meta["data_hash"] == data_hash(LOADED)
    assert meta["models_snapshot_date"] == "2026-11-05"
    assert meta["targets"][0]["params_sent"] == FAKE_TARGET.params
    assert meta["prompt_version"] == "stub" and meta["scorer_version"] == "1.2"
    assert meta["normaliser_version"] == "2"
    assert meta["follow_up_rule"] == "v1"
    assert meta["finished_at"] is not None
    assert meta["totals"]["items"] == TOTAL and meta["totals"]["calls"] > TOTAL
    assert meta["totals"]["uncached_calls"] == meta["totals"]["calls"]
    assert "git_sha" in meta and "git_dirty" in meta
    tools = json.loads((run_dir / "tools.json").read_text(encoding="utf-8"))
    assert sorted(tools) == ["banking", "clinic"]
    assert [t["name"] for t in tools["banking"]][:1] == ["get_balance"]


async def test_order_keeps_a_scenarios_columns_together(tmp_path: Path) -> None:
    items = plan_items(LOADED[:2], COLUMNS, [fake_target()], 2)
    assert [(i.loaded.scenario.id, i.repeat, i.column) for i in items[:7]] == [
        (LOADED[0].scenario.id, 1, column) for column in COLUMNS
    ] + [(LOADED[0].scenario.id, 2, "en")]


def test_should_run() -> None:
    assert should_run(None, retry_errors=False)
    assert not should_run({"status": "done", "outcome": "ok"}, retry_errors=True)
    assert not should_run({"status": "error", "outcome": "provider_error"}, retry_errors=False)
    assert should_run({"status": "error", "outcome": "provider_error"}, retry_errors=True)
    assert should_run({"status": "error", "outcome": "quota"}, retry_errors=False)


async def test_budget_stop_then_resume_after_a_truncated_trace(tmp_path: Path) -> None:
    budget = CallBudget(25)
    stopped = await go(tmp_path, [fake_target(budget=budget)], budget=budget)
    assert stopped.exit_code == EXIT_BUDGET and stopped.stopped == "budget"
    run_dir = tmp_path / "r1"
    meta = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["stopped"] == "budget" and meta["budget_used"] == 25
    done = keys_in_traces(run_dir)
    assert 0 < len(done) < TOTAL and len(done) == stopped.written
    assert set(read_index(run_dir)) == set(done)  # the item in flight stayed non-terminal

    # a crash while writing the next line leaves half a record behind
    first = (run_dir / TRACES_FILE).read_text(encoding="utf-8").splitlines()[0]
    with (run_dir / TRACES_FILE).open("a", encoding="utf-8") as handle:
        handle.write(first[: len(first) // 3])

    resumed = await go(tmp_path, resume=True)
    assert resumed.exit_code == EXIT_OK and resumed.stopped is None
    assert resumed.skipped == len(done) and resumed.written == TOTAL - len(done)
    keys = keys_in_traces(run_dir)
    assert len(keys) == len(set(keys)) == TOTAL  # nothing written twice
    raw = (run_dir / TRACES_FILE).read_bytes()
    assert raw.endswith(b"\n") and len(raw.splitlines()) == TOTAL
    index = read_index(run_dir)
    assert sorted(entry["line"] for entry in index.values()) == list(range(1, TOTAL + 1))
    meta = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["stopped"] is None and len(meta["resumed_at"]) == 1


async def test_budget_zero_writes_nothing(tmp_path: Path) -> None:
    budget = CallBudget(0)
    result = await go(tmp_path, [fake_target(budget=budget)], budget=budget)
    assert result.exit_code == EXIT_BUDGET and result.written == 0
    assert read_index(tmp_path / "r1") == {}


async def test_retry_errors_reruns_provider_errors_only(tmp_path: Path) -> None:
    broken = {
        "clinic-9001|egy": Override(mode="error_200"),
        "banking-9002": Override(mode="http_403"),
    }
    first = await go(tmp_path, [fake_target(broken)])
    assert first.outcomes == {"ok": TOTAL - 7, "provider_error": 1, "blocked_by_provider": 6}
    run_dir = tmp_path / "r1"
    key = "clinic-9001|egy|fake|1"
    entry = read_index(run_dir)[key]
    assert (entry["status"], entry["outcome"]) == ("error", "provider_error")

    plain = await go(tmp_path, resume=True)
    assert plain.written == 0 and plain.skipped == TOTAL

    retried = await go(tmp_path, resume=True, retry_errors=True)
    assert retried.written == 1 and retried.outcomes == {"ok": 1}
    index = read_index(run_dir)
    assert index[key] == {"status": "done", "outcome": "ok", "line": TOTAL + 1}
    assert keys_in_traces(run_dir).count(key) == 2  # a new line; the index points to it
    # blocked_by_provider is terminal and never retried
    assert index["banking-9002|egy|fake|1"]["outcome"] == "blocked_by_provider"


async def test_quota_stops_the_target_and_resume_reruns_it(tmp_path: Path) -> None:
    quota = {"clinic-9001|msa": Override(mode="quota")}
    clinic_first = [item for item in LOADED if item.scenario.id == "clinic-9001"] + [
        item for item in LOADED if item.scenario.id != "clinic-9001"
    ]
    result = await go(tmp_path, [fake_target(quota)], scenarios=clinic_first)
    assert result.exit_code == EXIT_QUOTA and result.stopped == "quota"
    assert result.target_stops == {"fake": "quota"}
    run_dir = tmp_path / "r1"
    assert keys_in_traces(run_dir) == ["clinic-9001|en|fake|1", "clinic-9001|msa|fake|1"]
    meta = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["stopped"] == "quota" and meta["target_stops"] == {"fake": "quota"}

    resumed = await go(tmp_path, scenarios=clinic_first, resume=True)
    assert resumed.exit_code == EXIT_OK
    assert resumed.written == TOTAL - 1  # the quota item again, and everything after it
    assert read_index(run_dir)["clinic-9001|msa|fake|1"]["outcome"] == "ok"


async def test_quota_on_one_target_does_not_stop_another(tmp_path: Path) -> None:
    other = RunTarget(FAKE_TARGET.model_copy(update={"name": "fake2"}), fake_factory())
    quota = fake_target({"*": Override(mode="quota")})
    result = await go(tmp_path, [quota, other])
    assert result.target_stops == {"fake": "quota"}
    assert result.outcomes == {"quota": 1, "ok": TOTAL}


class Drifting:
    """The fake with a response model that changes after `after` calls."""

    calls = 0

    def __init__(self, scenario: Scenario, column: Column, after: int) -> None:
        self.inner = FakeModel(scenario, column)
        self.after = after

    async def complete(self, request: Request) -> Completion:
        Drifting.calls += 1
        completion = await self.inner.complete(request)
        if Drifting.calls > self.after:
            return completion.model_copy(update={"response_model": "afandem/fake-oracle-v2"})
        return completion


@pytest.mark.parametrize("strict", [False, True])
async def test_model_drift_is_flagged_and_strict_drift_stops(tmp_path: Path, strict: bool) -> None:
    Drifting.calls = 0
    target = RunTarget(FAKE_TARGET, lambda scenario, column, _repeat: Drifting(scenario, column, 4))
    result = await go(tmp_path, [target], strict_drift=strict)
    run_dir = tmp_path / "r1"
    flags = [r["flags"] for _, r in read_traces(run_dir)]
    assert flags[0] == [] and ["model_drift"] in flags
    meta = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["drift_baseline"]["fake"]["response_model"] == "afandem/fake-oracle"
    if strict:
        assert result.exit_code == EXIT_DRIFT and result.stopped == "drift"
        assert len(flags) < TOTAL
    else:
        assert result.exit_code == EXIT_OK and len(flags) == TOTAL


async def test_concurrency_and_repeats(tmp_path: Path) -> None:
    result = await go(tmp_path, concurrency=4, repeats=2)
    assert result.written == 2 * TOTAL and result.outcomes == {"ok": 2 * TOTAL}
    keys = keys_in_traces(tmp_path / "r1")
    assert len(set(keys)) == 2 * TOTAL
    assert {k.rsplit("|", 1)[1] for k in keys} == {"1", "2"}


async def test_columns_subset(tmp_path: Path) -> None:
    result = await go(tmp_path, columns=["egy", "en"])
    assert result.written == len(LOADED) * 2
    assert {k.split("|")[1] for k in keys_in_traces(tmp_path / "r1")} == {"egy", "en"}


async def test_a_fresh_run_refuses_an_existing_run_dir(tmp_path: Path) -> None:
    await go(tmp_path, columns=["en"])
    with pytest.raises(RunExistsError):
        await go(tmp_path, columns=["en"])
    assert (tmp_path / "r1" / INDEX_FILE).exists()


def test_models_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text('{"snapshot": "models-2027-01-02.json"}', encoding="utf-8")
    assert models_snapshot(path) == ("models-2027-01-02.json", "2027-01-02")
    assert models_snapshot(tmp_path / "missing.json") == (None, None)


def test_duplicate_target_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate target"):
        Runner(LOADED, [fake_target(), fake_target()], options(tmp_path))


class FingerprintChurn:
    """The fake with a new `system_fingerprint` on every call (as Groq does)."""

    calls = 0

    def __init__(self, scenario: Scenario, column: Column) -> None:
        self.inner = FakeModel(scenario, column)

    async def complete(self, request: Request) -> Completion:
        FingerprintChurn.calls += 1
        completion = await self.inner.complete(request)
        return completion.model_copy(update={"system_fingerprint": f"fp_{FingerprintChurn.calls}"})


async def test_fingerprint_churn_is_not_drift(tmp_path: Path) -> None:
    FingerprintChurn.calls = 0
    target = RunTarget(
        FAKE_TARGET, lambda scenario, column, _repeat: FingerprintChurn(scenario, column)
    )
    result = await go(tmp_path, [target], strict_drift=True)
    assert result.exit_code == EXIT_OK
    assert not any("model_drift" in r["flags"] for _, r in read_traces(tmp_path / "r1"))
