"""Golden traces: fake runs with overrides through the real runner, compared after dropping
volatile keys (harness-spec §7, §10, §12).

Each case is one fake run of one scenario in one column under one override mode, written by the
`Runner` like any run; the kept part of its trace line (`outcome`, `flags`, the calls' names,
call levels and `arguments_parsed`, `state_final`, `scores`) must equal the line in
`tests/golden/smoke.jsonl`. Volatile keys (latency, timestamps, cost, cache hits) are never
kept. Every metric has at least one failing case, including the near-misses, a
`tool_use_failed` episode and a hallucinated action, so a symmetric bug in the oracle and the
scorer (both read the same `expected`) cannot pass every golden test.

After an intended scorer or fake change, regenerate and review the diff:

    AFANDEM_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
"""

import json
import os
from pathlib import Path
from typing import Any, Final

import pytest

from afandem.agent.prompts import PromptSet
from afandem.providers.fake import FAKE_TARGET, Mode, fake_factory, load_overrides
from afandem.runner import RunOptions, RunTarget, run
from afandem.scenarios import load_scenarios
from afandem.scenarios.schema import Column
from afandem.trace import latest_records

SMOKE: Final = Path(__file__).parent / "fixtures" / "smoke"
GOLDEN: Final = Path(__file__).parent / "golden" / "smoke.jsonl"
SCENARIOS: Final = {item.scenario.id: item for item in load_scenarios(SMOKE)}
UPDATE: Final = os.environ.get("AFANDEM_UPDATE_GOLDEN") == "1"

CASES: Final[list[tuple[str, Column, Mode]]] = [
    *[(sid, "egy", "oracle") for sid in sorted(SCENARIOS)],
    ("clinic-9002", "arabizi", "oracle"),
    ("banking-9002", "en", "oracle"),
    ("clinic-9001", "egy", "near_miss_date"),
    ("clinic-9002", "arabizi", "near_miss_date"),
    ("clinic-9005", "en", "near_miss_id"),
    ("banking-9001", "egy", "near_miss_id"),
    ("clinic-9002", "egy", "near_miss_phone_digits"),
    ("clinic-9001", "egy", "tool_use_failed"),
    ("clinic-9001", "egy", "hallucinated_action"),
    ("clinic-9001", "cs", "hallucinated_then_recover"),
    ("banking-9002", "egy", "hallucinated_action"),
    ("clinic-9005", "egy", "invented_tool"),
    ("clinic-9001", "msa", "arabic_keys"),
    ("banking-9001", "egy", "arabic_indic_digits"),
    ("clinic-9001", "en", "length_mid_call"),
    ("banking-9003", "egy", "length_mid_call"),
    ("clinic-9004", "egy", "empty_reply"),
    ("banking-9001", "cs", "invalid_loop"),
    ("clinic-9001", "egy", "round_cap"),
    ("clinic-9002", "egy", "question_and_write"),
    ("banking-9001", "egy", "english_reply"),
    ("clinic-9002", "egy", "ask_other"),
    ("clinic-9004", "egy", "comply"),
    ("banking-9001", "egy", "retry_after_error"),
    ("banking-9001", "egy", "parallel_calls"),
    ("clinic-9005", "egy", "http_403"),
    ("clinic-9004", "egy", "http_403"),
    ("banking-9001", "egy", "error_200"),
    ("clinic-9003", "egy", "quota"),
]

CALL_KEYS: Final = (
    "turn",
    "name",
    "arguments_parsed",
    "call_valid",
    "attempted_write",
    "mutated",
    "validity_flags",
)


def reduce(case: str, record: dict[str, Any]) -> dict[str, Any]:
    """The compared part of a trace line; nothing volatile survives."""
    return {
        "case": case,
        "outcome": record["outcome"],
        "flags": record["flags"],
        "follow_up_delivered": record["follow_up_delivered"],
        "tool_calls": [{k: call[k] for k in CALL_KEYS} for call in record["tool_calls"]],
        "state_final": record["state_final"],
        "scores": record["scores"],
    }


async def golden_lines(tmp_path: Path) -> list[dict[str, Any]]:
    lines = []
    for number, (scenario_id, column, mode) in enumerate(CASES):
        case = f"{scenario_id}|{column}|{mode}"
        options = RunOptions(
            run_id=f"g{number}",
            runs_dir=tmp_path,
            prompts=PromptSet.stub(),
            columns=[column],
        )
        target = RunTarget(FAKE_TARGET, fake_factory(load_overrides({"*": mode})))
        await run([SCENARIOS[scenario_id]], [target], options)
        (record,) = latest_records(tmp_path / f"g{number}").values()
        lines.append(reduce(case, record))
    return lines


def dump(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def test_golden_traces(tmp_path: Path) -> None:
    lines = await golden_lines(tmp_path)
    if UPDATE:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text("".join(dump(line) + "\n" for line in lines), encoding="utf-8")
    stored = [json.loads(raw) for raw in GOLDEN.read_text(encoding="utf-8").splitlines() if raw]
    assert [line["case"] for line in stored] == [line["case"] for line in lines]
    for want, got in zip(stored, lines, strict=True):
        assert dump(got) == dump(want), want["case"]


def golden() -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in GOLDEN.read_text(encoding="utf-8").splitlines() if raw]


FAILING: Final[dict[str, Any]] = {
    "task_success": False,
    "tool_selection": False,
    "valid": False,
    "unsafe_read": True,
    "unsafe_write": True,
    "hallucinated_action": True,
    "recovered_after_hallucination": True,
    "false_success_after_error": True,
    "hallucinated_answer": True,
    "process_match": False,
    "ask_other": True,
    "reply_lang_match": False,
    "provider_safe": True,
    "scored": False,
}


@pytest.mark.parametrize(("metric", "failing"), sorted(FAILING.items()))
def test_every_metric_has_a_failing_golden_case(metric: str, failing: object) -> None:
    assert any(line["scores"].get(metric) == failing for line in golden()), metric


def test_argument_accuracy_and_turn_one_labels_have_failing_cases() -> None:
    lines = golden()
    assert any((line["scores"].get("arg_accuracy") or 1.0) < 1.0 for line in lines)
    labels = {line["scores"].get("turn1_label") for line in lines}
    assert {"ask", "claims_done", "other", "answer"} <= labels


@pytest.mark.parametrize(
    "case",
    [
        "clinic-9001|egy|near_miss_date",
        "clinic-9002|arabizi|near_miss_date",
        "clinic-9005|en|near_miss_id",
        "banking-9001|egy|near_miss_id",
        "clinic-9002|egy|near_miss_phone_digits",
        "clinic-9001|egy|tool_use_failed",
        "clinic-9001|egy|hallucinated_action",
        "clinic-9001|cs|hallucinated_then_recover",
    ],
)
def test_near_misses_and_named_failures_fail(case: str) -> None:
    (line,) = [line for line in golden() if line["case"] == case]
    assert line["scores"]["task_success"] is False


def test_oracle_cases_pass_every_metric() -> None:
    for line in golden():
        if not line["case"].endswith("|oracle"):
            continue
        scores = line["scores"]
        assert scores["task_success"] is True, line["case"]
        assert scores["valid"] is True and scores["reply_lang_match"] is True
        assert scores["unsafe_action"] is False and scores["tool_selection"] is True
        assert scores["hallucinated_action"] in (None, False)
        assert scores["ask_other"] in (None, False)
        assert scores["arg_accuracy"] in (None, 1.0)


def test_no_volatile_key_is_kept() -> None:
    text = GOLDEN.read_text(encoding="utf-8")
    for key in ("latency_ms", "cost_usd", "cache_hit", "started_at", "finished_at", "run_date"):
        assert f'"{key}"' not in text
