"""`afandem score RUN_DIR`: re-score a run from its traces, offline, with the current scenarios.

`traces.jsonl` is never touched. The latest line of every item (the one `index.json` points to)
is read back (`EpisodeView`), scored against the scenario file as it is now, and written to
`RUN_DIR/scores.jsonl`: one line per item key, sorted by key, replaced atomically. No provider
is called; scoring needs nothing but the trace and the scenario.

A trace whose `scenario_sha256` differs from the current file is still scored (against the
current file) and warned about once per line; a trace whose scenario is not found is warned
about and left out. A gold the replay cannot reach raises `AcceptableSetError` before anything
is written.
"""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from afandem.scenarios import LoadedScenario
from afandem.scoring import (
    NORMALISER_VERSION,
    SCORER_VERSION,
    EpisodeView,
    Gold,
    prepare_gold,
    score_episode,
)
from afandem.trace import dumps_line, latest_records, read_index

SCORES_FILE: Final = "scores.jsonl"

type Warn = Callable[[str], None]


@dataclass
class RescoreResult:
    path: Path
    items: int = 0
    scored: int = 0
    excluded: int = 0
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def _line(
    record: Mapping[str, Any], key: str, number: int, loaded: LoadedScenario, gold: Gold
) -> dict[str, Any]:
    scenario = loaded.scenario
    scores = score_episode(scenario, EpisodeView.from_record(record), gold=gold)
    return {
        "key": key,
        "line": number,
        "scenario_id": scenario.id,
        "column": record["column"],
        "target": record["target"],
        "repeat": record["repeat"],
        "behaviour": scenario.behaviour,
        "outcome": record["outcome"],
        "scorer_version": SCORER_VERSION,
        "normaliser_version": NORMALISER_VERSION,
        "scenario_sha256": loaded.sha256,
        "trace_scenario_sha256": record.get("scenario_sha256"),
        "scenario_changed": record.get("scenario_sha256") != loaded.sha256,
        "scores": scores.model_dump(mode="json"),
    }


def rescore_run(
    run_dir: Path, scenarios: Sequence[LoadedScenario], *, warn: Warn | None = None
) -> RescoreResult:
    """Score every item of a run directory into `scores.jsonl`."""
    say = warn or (lambda message: None)
    by_id = {item.scenario.id: item for item in scenarios}
    golds: dict[str, Gold] = {}
    index = read_index(run_dir)
    records = latest_records(run_dir)
    result = RescoreResult(run_dir / SCORES_FILE)
    lines: list[dict[str, Any]] = []
    for key in sorted(records):
        record = records[key]
        number = int(index[key]["line"])
        scenario_id = str(record["scenario_id"])
        loaded = by_id.get(scenario_id)
        if loaded is None:
            say(f"line {number} ({key}): scenario {scenario_id} not found; not scored")
            result.missing.append(key)
            continue
        if record.get("scenario_sha256") != loaded.sha256:
            say(
                f"line {number} ({key}): scenario_sha256 differs from the trace "
                f"({str(record.get('scenario_sha256'))[:12]} -> {loaded.sha256[:12]}); "
                "scored against the current file"
            )
            result.changed.append(key)
        if scenario_id not in golds:
            golds[scenario_id] = prepare_gold(loaded.scenario)
        line = _line(record, key, number, loaded, golds[scenario_id])
        lines.append(line)
        result.items += 1
        result.scored += bool(line["scores"]["scored"])
        result.excluded += not line["scores"]["scored"]
    temporary = result.path.with_name(f".{SCORES_FILE}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(dumps_line(line) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, result.path)
    return result


def read_scores(run_dir: Path) -> dict[str, dict[str, Any]]:
    """`scores.jsonl` keyed by item key; {} when the run has not been re-scored."""
    path = run_dir / SCORES_FILE
    if not path.exists():
        return {}
    found: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                line = json.loads(raw)
                found[str(line["key"])] = line
    return found


__all__ = ["SCORES_FILE", "RescoreResult", "read_scores", "rescore_run"]
