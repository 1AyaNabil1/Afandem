"""Run directory files: append + fsync, the atomic index, crash recovery, Arabic verbatim."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from afandem.scoring import Scores
from afandem.trace import (
    INDEX_FILE,
    TRACES_FILE,
    RunExistsError,
    RunWriter,
    TraceCorruptError,
    TraceRecord,
    item_key,
    item_status,
    latest_records,
    read_index,
    read_traces,
    run_totals,
    write_json_atomic,
    write_tools,
)

ARABIC = "\N{ARABIC LETTER MEEM}\N{ARABIC LETTER NOON}\N{ARABIC LETTER ALEF MAKSURA}"


def record(scenario_id: str = "clinic-9001", *, outcome: str = "ok", **extra: Any) -> TraceRecord:
    data: dict[str, Any] = {
        "prompt_version": "stub",
        "scorer_version": "0.1",
        "run_id": "r",
        "run_date": "2026-11-05",
        "started_at": "2026-11-05T00:00:00+00:00",
        "finished_at": "2026-11-05T00:00:01+00:00",
        "scenario_id": scenario_id,
        "scenario_sha256": "0" * 64,
        "revision": 1,
        "authoring_batch": "pilot",
        "domain": "clinic",
        "behaviour": "act",
        "column": "egy",
        "target": "fake",
        "route": "fake",
        "model": "m",
        "provider_served": None,
        "response_model": None,
        "system_fingerprint": None,
        "params_sent": {},
        "provider_prefs": {},
        "repeat": 1,
        "salt": None,
        "messages": [{"role": "user", "content": ARABIC}],
        "tool_calls": [],
        "state_initial": {},
        "state_final": {},
        "expected_state": {},
        "usage": [],
        "turns": [],
        "follow_up_rule": "v1",
        "follow_up_delivered": False,
        "finish_reasons": [],
        "outcome": outcome,
        "outcome_detail": None,
        "flags": [],
        "scores": Scores(scored=outcome == "ok"),
    }
    data.update(extra)
    return TraceRecord.model_validate(data)


def test_record_has_the_schema_fields() -> None:
    dumped = record().model_dump(mode="json")
    assert dumped["trace_schema"] == 2
    for name in ("normaliser_version", "judge_version", "probe_version"):
        assert dumped[name] is None
    assert dumped["scores"]["judge"] is None and dumped["scores"]["probe"] is None


def test_item_key_and_status() -> None:
    assert item_key("clinic-9001", "egy", "fake", 2) == "clinic-9001|egy|fake|2"
    assert record().key == "clinic-9001|egy|fake|1"
    assert [item_status(o) for o in ("ok", "blocked_by_provider", "provider_error", "quota")] == [
        "done",
        "done",
        "error",
        "error",
    ]


def test_write_appends_syncs_and_indexes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    with RunWriter(tmp_path) as writer:
        assert writer.write(record("clinic-9001")) == 1
        assert writer.write(record("clinic-9002", outcome="provider_error")) == 2
    assert len(synced) >= 4  # each line and each index rewrite
    index = read_index(tmp_path)
    assert index == {
        "clinic-9001|egy|fake|1": {"status": "done", "outcome": "ok", "line": 1},
        "clinic-9002|egy|fake|1": {"status": "error", "outcome": "provider_error", "line": 2},
    }
    text = (tmp_path / TRACES_FILE).read_text(encoding="utf-8")
    assert ARABIC in text and "\\u06" not in text
    assert not list(tmp_path.glob(".*.tmp"))


def test_a_rewritten_item_points_the_index_to_the_latest_line(tmp_path: Path) -> None:
    with RunWriter(tmp_path) as writer:
        writer.write(record(outcome="provider_error"))
        writer.write(record())
    assert read_index(tmp_path)["clinic-9001|egy|fake|1"] == {
        "status": "done",
        "outcome": "ok",
        "line": 2,
    }
    (latest,) = latest_records(tmp_path).values()
    assert latest["outcome"] == "ok"


def test_a_fresh_run_refuses_a_directory_with_traces(tmp_path: Path) -> None:
    with RunWriter(tmp_path) as writer:
        writer.write(record())
    with pytest.raises(RunExistsError, match="--resume"):
        RunWriter(tmp_path)
    RunWriter(tmp_path, resume=True).close()


def test_a_partial_last_line_is_dropped_on_resume(tmp_path: Path) -> None:
    with RunWriter(tmp_path) as writer:
        writer.write(record("clinic-9001"))
    line = json.dumps(record("clinic-9002").model_dump(mode="json"), ensure_ascii=False)
    with (tmp_path / TRACES_FILE).open("a", encoding="utf-8") as handle:
        handle.write(line[: len(line) // 2])  # the crash cut the line
    assert [n for n, _ in read_traces(tmp_path)] == [1]
    with RunWriter(tmp_path, resume=True) as writer:
        assert writer.lines == 1
        assert writer.write(record("clinic-9002")) == 2
    lines = (tmp_path / TRACES_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(raw)["scenario_id"] for raw in lines] == ["clinic-9001", "clinic-9002"]


def test_a_complete_unindexed_line_is_adopted_not_rerun(tmp_path: Path) -> None:
    with RunWriter(tmp_path) as writer:
        writer.write(record("clinic-9001"))
    line = json.dumps(record("clinic-9002").model_dump(mode="json"), ensure_ascii=False)
    with (tmp_path / TRACES_FILE).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")  # the crash fell between the line and the index
    assert "clinic-9002|egy|fake|1" not in read_index(tmp_path)
    with RunWriter(tmp_path, resume=True) as writer:
        assert writer.index["clinic-9002|egy|fake|1"]["line"] == 2
    assert read_index(tmp_path)["clinic-9002|egy|fake|1"]["status"] == "done"


def test_a_corrupt_complete_line_is_an_error(tmp_path: Path) -> None:
    (tmp_path / TRACES_FILE).write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(TraceCorruptError, match=":1:"):
        RunWriter(tmp_path, resume=True)


def test_index_rewrite_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with RunWriter(tmp_path) as writer:
        writer.write(record("clinic-9001"))
        before = (tmp_path / INDEX_FILE).read_text(encoding="utf-8")

        def broken_replace(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", broken_replace)
        with pytest.raises(OSError, match="disk full"):
            writer.write(record("clinic-9002"))
    assert (tmp_path / INDEX_FILE).read_text(encoding="utf-8") == before
    assert json.loads(before)["items"].keys() == {"clinic-9001|egy|fake|1"}
    monkeypatch.undo()
    # the line made it to disk; resuming adopts it instead of running the item again
    with RunWriter(tmp_path, resume=True) as writer:
        assert writer.index["clinic-9002|egy|fake|1"]["line"] == 2


def test_write_json_atomic_and_tools(tmp_path: Path) -> None:
    write_json_atomic(tmp_path / "x.json", {"b": ARABIC, "a": 1})
    text = (tmp_path / "x.json").read_text(encoding="utf-8")
    assert ARABIC in text and text.index('"a"') < text.index('"b"')
    write_tools(tmp_path, {"clinic": '[{"name":"t"}]'})
    assert json.loads((tmp_path / "tools.json").read_text(encoding="utf-8")) == {
        "clinic": [{"name": "t"}]
    }


def test_run_totals_count_every_attempt(tmp_path: Path) -> None:
    usage = {
        "turn": 1,
        "round": 1,
        "finish_reason": "stop",
        "finish_reason_raw": "stop",
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "reasoning_tokens": None,
        "cost_usd": 0.5,
        "cost_source": "x",
        "latency_ms": 1,
        "cache_hit": False,
        "cache_key": None,
        "response_id": None,
        "response_model": None,
        "system_fingerprint": None,
        "provider_served": None,
        "tool_calls": 0,
    }
    with RunWriter(tmp_path) as writer:
        writer.write(record(outcome="provider_error", usage=[usage]))
        writer.write(record(usage=[usage, {**usage, "cache_hit": True}]))
    totals = run_totals(tmp_path)
    assert totals["lines"] == 2 and totals["items"] == 1
    assert totals["calls"] == 3 and totals["uncached_calls"] == 2
    assert totals["prompt_tokens"] == 30 and totals["cost_usd"] == 1.5
    assert totals["outcomes"] == {"ok": 1, "provider_error": 1}
