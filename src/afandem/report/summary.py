"""`summary.json`: the descriptive numbers of one run (docs/harness-spec.md §11, Phase 1 part).

Descriptive only: counts, rates and raw paired differences, no confidence intervals or tests
(the cluster bootstrap and mid-p McNemar are Phase 3). Scores come from `scores.jsonl` when the
run was re-scored (`afandem score`), else from the trace lines when they carry the current
`scorer_version`; a run scored by an older scorer must be re-scored first.

Sets. The **primary set** is `act`, `inform`, `ask` and `none` (controls are `act`/`inform` items
and are in it); **harmful** is `refuse`; `out_of_scope` is reported on its own. Task success is
the share of items with a programmatic outcome (unscored exclusions and provider-safe harmful
items have none). **Gaps** are EGY minus MSA and EGY minus EN in points, on pairwise-complete
(scenario, repeat) pairs of the primary set, per target: raw differences, descriptive.

Drafts. A scenario is a draft when any of its texts (or its `arabizi_variant`) carries
`provenance: "assistant_draft"`; the count comes from the scenario files, and the report states
that items from drafts are not measured results.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from afandem import __version__
from afandem.scenarios import COLUMNS, LoadedScenario, Scenario
from afandem.scoring import NORMALISER_VERSION, SCORER_VERSION
from afandem.scoring.actions import VALIDITY_FLAGS
from afandem.scoring.behaviour import TURN1_LABELS
from afandem.scoring.rescore import read_scores
from afandem.trace import RUN_FILE, latest_records, read_json

PRIMARY: Final = ("act", "inform", "ask", "none")
HARMFUL: Final = ("refuse",)
EXCLUDED: Final = ("provider_error", "quota", "context_overflow")
HARNESS_FLAGS: Final = (
    "length",
    "invalid_loop",
    "tool_use_failed",
    "truncated_tool_call",
    "round_cap_hit",
    "empty_reply",
    "deadline",
    "model_drift",
)
GAPS: Final = (("egy_minus_msa", "egy", "msa"), ("egy_minus_en", "egy", "en"))
REPLY_EXCERPT: Final = 240


class StaleScoresError(Exception):
    """The run's scores come from another scorer version and it was not re-scored."""


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    scenario_id: str
    column: str
    target: str
    repeat: int
    behaviour: str
    outcome: str
    flags: tuple[str, ...]
    scores: Mapping[str, Any]
    turn1: str


def is_draft(scenario: Scenario) -> bool:
    texts = [block.provenance for _, block in scenario.texts.columns()]
    if scenario.arabizi_variant is not None:
        texts.append(scenario.arabizi_variant.provenance)
    return "assistant_draft" in texts


def _turn1(record: Mapping[str, Any]) -> str:
    for turn in record.get("turns") or []:
        if turn.get("turn") == 1:
            return str(turn.get("text") or "")
    return ""


def load_items(run_dir: Path) -> tuple[list[Item], str]:
    """The run's items with their scores and where the scores came from."""
    records = latest_records(run_dir)
    rescored = read_scores(run_dir)
    source = "scores.jsonl" if rescored else "traces.jsonl"
    items: list[Item] = []
    for key in sorted(records):
        record = records[key]
        if rescored:
            line = rescored.get(key)
            if line is None:
                continue  # not scored (its scenario is missing): reported by `afandem score`
            scores, behaviour = line["scores"], str(line["behaviour"])
        else:
            if record.get("scorer_version") != SCORER_VERSION:
                raise StaleScoresError(
                    f"{run_dir}: traces scored by scorer {record.get('scorer_version')}, "
                    f"current is {SCORER_VERSION}; run `afandem score {run_dir}` first"
                )
            scores, behaviour = record["scores"], str(record["behaviour"])
        items.append(
            Item(
                key=key,
                scenario_id=str(record["scenario_id"]),
                column=str(record["column"]),
                target=str(record["target"]),
                repeat=int(record["repeat"]),
                behaviour=behaviour,
                outcome=str(record["outcome"]),
                flags=tuple(record.get("flags") or ()),
                scores=scores,
                turn1=_turn1(record),
            )
        )
    return items, source


def _rate(values: Iterable[bool | None]) -> dict[str, Any]:
    known = [bool(v) for v in values if v is not None]
    return {
        "n": len(known),
        "successes": sum(known),
        "rate": round(sum(known) / len(known), 4) if known else None,
    }


def _mean(values: Iterable[float | bool | None]) -> float | None:
    known = [float(v) for v in values if v is not None]
    return round(sum(known) / len(known), 4) if known else None


def _cells(items: Sequence[Item], value: Any) -> dict[str, dict[str, Any]]:
    grid: dict[str, dict[str, list[Item]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        grid[item.target][item.column].append(item)
    return {
        target: {col: value(grid[target][col]) for col in COLUMNS if col in grid[target]}
        for target in sorted(grid)
    }


def _success(items: Sequence[Item]) -> dict[str, Any]:
    return _rate(item.scores.get("task_success") for item in items)


def _gaps(items: Sequence[Item]) -> dict[str, dict[str, Any]]:
    by_target: dict[str, dict[tuple[str, int], dict[str, bool]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for item in items:
        success = item.scores.get("task_success")
        if success is not None:
            by_target[item.target][(item.scenario_id, item.repeat)][item.column] = bool(success)
    out: dict[str, dict[str, Any]] = {}
    for target in sorted(by_target):
        out[target] = {}
        for name, left, right in GAPS:
            pairs = [p for p in by_target[target].values() if left in p and right in p]
            points = (
                round(100 * sum(p[left] - p[right] for p in pairs) / len(pairs), 1)
                if pairs
                else None
            )
            out[target][name] = {"points": points, "pairs": len(pairs)}
    return out


def _metrics(items: Sequence[Item]) -> dict[str, Any]:
    scored = [i for i in items if i.scores.get("scored")]

    def count(name: str, wanted: object = True) -> int:
        return sum(1 for i in scored if i.scores.get(name) is wanted)

    return {
        "scored": len(scored),
        "tool_selection": _mean(i.scores.get("tool_selection") for i in scored),
        "arg_accuracy": _mean(i.scores.get("arg_accuracy") for i in scored),
        "valid_rate": _mean(i.scores.get("valid") for i in scored),
        "reply_lang_match": _rate(i.scores.get("reply_lang_match") for i in scored),
        "hallucinated_action": count("hallucinated_action"),
        "recovered_after_hallucination": count("recovered_after_hallucination"),
        "false_success_after_error": count("false_success_after_error"),
        "hallucinated_answer": count("hallucinated_answer"),
        "unsafe_read": count("unsafe_read"),
        "unsafe_write": count("unsafe_write"),
        "ask_other": count("ask_other"),
        "right_state_other_path": count("process_match", False),
    }


def _validity(items: Sequence[Item]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for item in items:
        counts = item.scores.get("validity")
        if isinstance(counts, Mapping):
            totals.update({flag: int(counts.get(flag) or 0) for flag in VALIDITY_FLAGS})
            totals["items_invalid"] += item.scores.get("valid") is False
    scored = sum(1 for i in items if i.scores.get("scored"))
    return {
        **{flag: totals[flag] for flag in (*VALIDITY_FLAGS, "items_invalid")},
        "items_scored": scored,
    }


def _flags(items: Sequence[Item]) -> dict[str, int]:
    counts = {flag: sum(1 for i in items if flag in i.flags) for flag in HARNESS_FLAGS}
    return {**counts, "items": len(items)}


def _labels(items: Sequence[Item]) -> dict[str, int]:
    counts = Counter(str(i.scores.get("turn1_label")) for i in items if i.scores.get("scored"))
    return {label: counts[label] for label in TURN1_LABELS}


def _exclusions(items: Sequence[Item]) -> dict[str, int]:
    outcomes = Counter(item.outcome for item in items)
    return {
        "items": len(items),
        "scored": sum(1 for i in items if i.scores.get("scored")),
        **{outcome: outcomes[outcome] for outcome in (*EXCLUDED, "blocked_by_provider")},
        "provider_safe": sum(1 for i in items if i.scores.get("provider_safe")),
    }


def _reason(scores: Mapping[str, Any]) -> str:
    reasons = [str(r) for r in scores.get("reasons") or []]
    text = "; ".join(reasons[:3]) + (f" (+{len(reasons) - 3})" if len(reasons) > 3 else "")
    return text or "-"


def _failures(items: Sequence[Item]) -> list[dict[str, Any]]:
    return [
        {
            "key": item.key,
            "scenario_id": item.scenario_id,
            "column": item.column,
            "target": item.target,
            "behaviour": item.behaviour,
            "reason": _reason(item.scores),
            "turn1_excerpt": item.turn1[:REPLY_EXCERPT],
        }
        for item in items
        if item.scores.get("task_success") is False
    ]


def _run_meta(run_dir: Path) -> dict[str, Any]:
    path = run_dir / RUN_FILE
    meta: dict[str, Any] = read_json(path) if path.exists() else {}
    keys = (
        "run_id",
        "started_at",
        "finished_at",
        "git_sha",
        "git_dirty",
        "data_hash",
        "prompt_version",
        "columns",
        "repeats",
        "models_snapshot",
        "follow_up_rule",
        "stopped",
    )
    out = {key: meta.get(key) for key in keys}
    out["run_id"] = out["run_id"] or run_dir.name
    out["trace_scorer_version"] = meta.get("scorer_version")
    out["parameters"] = [
        {
            "name": t.get("name"),
            "route": t.get("route"),
            "model": t.get("model"),
            "params_sent": t.get("params_sent"),
            "provider_prefs": t.get("provider_prefs"),
        }
        for t in meta.get("targets") or []
    ]
    return out


def _drafts(items: Sequence[Item], scenarios: Sequence[LoadedScenario]) -> dict[str, Any]:
    by_id = {loaded.scenario.id: loaded.scenario for loaded in scenarios}
    ids = sorted({item.scenario_id for item in items})
    drafts = [sid for sid in ids if sid in by_id and is_draft(by_id[sid])]
    return {
        "scenarios": len(ids),
        "draft_scenarios": len(drafts),
        "draft_ids": drafts,
        "draft_items": sum(1 for item in items if item.scenario_id in drafts),
        "items": len(items),
        "unknown_scenarios": [sid for sid in ids if sid not in by_id],
    }


def build_summary(run_dir: Path, scenarios: Sequence[LoadedScenario]) -> dict[str, Any]:
    """Every number of the descriptive report, JSON-ready."""
    items, source = load_items(run_dir)
    primary = [i for i in items if i.behaviour in PRIMARY]
    columns = [c for c in COLUMNS if any(i.column == c for i in items)]
    return {
        "summary_schema": 1,
        "descriptive_only": True,
        "generated_by": {
            "afandem": __version__,
            "scorer_version": SCORER_VERSION,
            "normaliser_version": NORMALISER_VERSION,
            "scores_from": source,
        },
        "run": _run_meta(run_dir),
        "columns": columns,
        "targets": sorted({i.target for i in items}),
        "drafts": _drafts(items, scenarios),
        "behaviours": dict(sorted(Counter(i.behaviour for i in items).items())),
        "task_success": {
            "primary": _cells(primary, _success),
            "inform": _cells([i for i in items if i.behaviour == "inform"], _success),
            "harmful": _cells([i for i in items if i.behaviour in HARMFUL], _success),
            "out_of_scope": _cells([i for i in items if i.behaviour == "out_of_scope"], _success),
            "all": _cells(items, _success),
        },
        "gaps_primary": _gaps(primary),
        "metrics": _cells(items, _metrics),
        "validity": _cells(items, _validity),
        "flags": _cells(items, _flags),
        "turn1_labels": _cells(items, _labels),
        "exclusions": _cells(items, _exclusions),
        "failures": _failures(items),
    }


__all__ = [
    "GAPS",
    "HARMFUL",
    "PRIMARY",
    "Item",
    "StaleScoresError",
    "build_summary",
    "is_draft",
    "load_items",
]
