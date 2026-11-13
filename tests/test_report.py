"""`afandem score` (re-scoring from traces), `afandem report` and the scores.jsonl preference of
`show` and `summary`."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from afandem.agent.prompts import PROMPTS_ENV
from afandem.cli import KEY_VARIABLES, main
from afandem.report import build_summary, render, write_report
from afandem.report.markdown import _share, table
from afandem.report.summary import StaleScoresError, is_draft, load_items
from afandem.scenarios import load_scenarios
from afandem.scoring import SCORER_VERSION
from afandem.scoring.rescore import SCORES_FILE, read_scores, rescore_run
from afandem.trace import TRACES_FILE

SMOKE = Path(__file__).parent / "fixtures" / "smoke"


@pytest.fixture(autouse=True)
def _no_keys_and_no_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(PROMPTS_ENV, str(tmp_path / "no-prompts"))


def fake_run(
    runs: Path, run_id: str, scenarios: Path = SMOKE, overrides: dict[str, str] | None = None
) -> Path:
    args = ["run", "--fake", "--scenarios", str(scenarios), "--runs-dir", str(runs)]
    args += ["--run-id", run_id, "--columns", "en,msa,egy"]
    if overrides:
        path = runs / f"{run_id}-overrides.json"
        runs.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(overrides), encoding="utf-8")
        args += ["--overrides", str(path)]
    assert main(args) == 0
    return runs / run_id


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drafted_copy(tmp_path: Path, scenario_id: str = "clinic-9001") -> Path:
    """The smoke fixtures with one scenario's EGY text marked as an assistant draft."""
    copy = tmp_path / "scenarios"
    shutil.copytree(SMOKE, copy)
    path = next(copy.rglob(f"{scenario_id}.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["texts"]["egy"]["provenance"] = "assistant_draft"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return copy


def make_v0(run_dir: Path) -> None:
    """Rewrite a run's trace lines as scorer 0.1 left them (what the live pilot run holds)."""
    lines = (run_dir / TRACES_FILE).read_text(encoding="utf-8").splitlines()
    old = []
    for raw in lines:
        record = json.loads(raw)
        record["scorer_version"] = "0.1"
        record["scores"] = {"scored": True, "task_success": None, "reasons": []}
        old.append(json.dumps(record, ensure_ascii=False))
    (run_dir / TRACES_FILE).write_text("\n".join(old) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- score


def test_rescoring_writes_scores_jsonl_and_leaves_traces_alone(tmp_path: Path) -> None:
    run_dir = fake_run(tmp_path / "runs", "r", overrides={"clinic-9001|egy": "near_miss_date"})
    before = digest(run_dir / TRACES_FILE)
    result = rescore_run(run_dir, load_scenarios(SMOKE))
    assert digest(run_dir / TRACES_FILE) == before
    scores = read_scores(run_dir)
    assert result.items == len(scores) == 27 and result.scored == 27 and not result.changed
    line = scores["clinic-9001|egy|fake|1"]
    assert line["scorer_version"] == SCORER_VERSION and line["normaliser_version"] == "2"
    assert line["scores"]["task_success"] is False and line["scenario_changed"] is False
    trace = json.loads((run_dir / TRACES_FILE).read_text(encoding="utf-8").splitlines()[0])
    assert scores[f"{trace['scenario_id']}|{trace['column']}|fake|1"]["scores"] == trace["scores"]
    assert read_scores(tmp_path) == {}


def test_rescoring_warns_per_line_on_a_changed_or_missing_scenario(tmp_path: Path) -> None:
    run_dir = fake_run(tmp_path / "runs", "r")
    changed = drafted_copy(tmp_path)
    (next(changed.rglob("banking-9004.json"))).unlink()
    warnings: list[str] = []
    result = rescore_run(run_dir, load_scenarios(changed), warn=warnings.append)
    assert len(result.changed) == 3 and len(result.missing) == 3
    assert sum("scenario_sha256 differs" in w for w in warnings) == 3
    assert sum("banking-9004 not found" in w for w in warnings) == 3
    assert all(w.startswith("line ") for w in warnings)
    assert read_scores(run_dir)["clinic-9001|egy|fake|1"]["scenario_changed"] is True


def test_score_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = fake_run(tmp_path / "runs", "r", overrides={"clinic-9005|en": "error_200"})
    capsys.readouterr()
    assert main(["score", str(run_dir), "--scenarios", str(drafted_copy(tmp_path))]) == 0
    out, err = capsys.readouterr()
    assert "scored 27 item(s) (26 scored, 1 excluded; 3 with a changed scenario" in out
    assert err.count("warning: line ") == 3
    assert (run_dir / SCORES_FILE).exists()
    assert main(["score", str(tmp_path / "missing")]) == 2
    assert main(["score", str(run_dir), "--scenarios", str(tmp_path / "none")]) == 2


def test_show_and_summary_prefer_scores_jsonl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = fake_run(tmp_path / "runs", "r")
    make_v0(run_dir)
    capsys.readouterr()
    assert main(["summary", str(run_dir)]) == 0
    assert "scores from traces" in capsys.readouterr().out
    assert main(["score", str(run_dir), "--scenarios", str(SMOKE)]) == 0
    capsys.readouterr()
    assert main(["summary", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "scores from scores.jsonl" in out
    assert out.splitlines()[2].split("|")[1].strip() == "9/9"
    assert main(["show", str(run_dir), "--scenario", "clinic-9002", "--column", "egy"]) == 0
    out = capsys.readouterr().out
    assert "score: task_success=True" in out
    assert "metrics (1.2): turn1=ask/phone hallucinated_action=False" in out


# ---------------------------------------------------------------- report


def test_summary_numbers(tmp_path: Path) -> None:
    run_dir = fake_run(
        tmp_path / "runs",
        "r",
        scenarios=drafted_copy(tmp_path),
        overrides={
            "clinic-9001|egy": "near_miss_date",
            "clinic-9002|egy": "hallucinated_action",
            "banking-9002|egy": "english_reply",
            "clinic-9004|en": "http_403",
            "clinic-9005|msa": "error_200",
            "banking-9001|egy": "invented_tool",
        },
    )
    summary = build_summary(run_dir, load_scenarios(drafted_copy(tmp_path / "again")))
    assert summary["descriptive_only"] is True
    assert summary["generated_by"]["scores_from"] == "traces.jsonl"
    assert summary["columns"] == ["en", "msa", "egy"] and summary["targets"] == ["fake"]
    assert summary["drafts"] == {
        "scenarios": 9,
        "draft_scenarios": 1,
        "draft_ids": ["clinic-9001"],
        "draft_items": 3,
        "items": 27,
        "unknown_scenarios": [],
    }
    primary = summary["task_success"]["primary"]["fake"]
    assert primary["en"] == {"n": 7, "successes": 7, "rate": 1.0}
    assert primary["msa"] == {"n": 6, "successes": 6, "rate": 1.0}  # error_200 excluded
    assert primary["egy"] == {"n": 7, "successes": 5, "rate": 0.7143}
    gaps = summary["gaps_primary"]["fake"]
    assert gaps["egy_minus_en"] == {"points": -28.6, "pairs": 7}
    assert gaps["egy_minus_msa"] == {"points": -33.3, "pairs": 6}
    assert summary["task_success"]["inform"]["fake"]["egy"]["n"] == 2
    harmful = summary["task_success"]["harmful"]["fake"]
    assert harmful["en"] == {"n": 0, "successes": 0, "rate": None}  # provider-safe only
    exclusions = summary["exclusions"]["fake"]
    assert exclusions["en"]["blocked_by_provider"] == 1 and exclusions["en"]["provider_safe"] == 1
    assert exclusions["msa"]["provider_error"] == 1 and exclusions["msa"]["scored"] == 8
    metrics = summary["metrics"]["fake"]["egy"]
    assert metrics["hallucinated_action"] == 1
    assert metrics["reply_lang_match"]["successes"] == 8
    assert summary["validity"]["fake"]["egy"]["invented_tool"] == 1
    assert summary["turn1_labels"]["fake"]["egy"]["claims_done"] >= 1
    failures = {(f["scenario_id"], f["column"]) for f in summary["failures"]}
    assert failures == {("clinic-9001", "egy"), ("clinic-9002", "egy")}
    assert [p["name"] for p in summary["run"]["parameters"]] == ["fake"]


def test_report_files_and_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scenarios = drafted_copy(tmp_path)
    run_dir = fake_run(
        tmp_path / "runs", "r", scenarios=scenarios, overrides={"clinic-9001|egy": "near_miss_date"}
    )
    results = tmp_path / "results"
    capsys.readouterr()
    args = ["report", str(run_dir), "--scenarios", str(scenarios), "--results-dir", str(results)]
    assert main(args) == 0
    assert "report:" in capsys.readouterr().out
    summary = json.loads((results / "r" / "summary.json").read_text(encoding="utf-8"))
    assert summary["run"]["run_id"] == "r"
    text = (results / "r" / "report.md").read_text(encoding="utf-8")
    assert text.startswith("# Afandem results: r\n\n> **Drafts, not measured results.** 1 of 9")
    assert "| fake | 7/7 (100%) | 7/7 (100%) | 6/7 (86%) | -14.3 pts (7 pairs) |" in text
    assert "## Inform items" in text and "## Parameters" in text
    assert "| clinic-9001 | egy | fake | act | state: appointments[a_9001].date;" in text
    assert '<div dir="rtl">[fake] done [' in text
    assert "`max_tokens=4096`" in text


def test_report_without_drafts_and_with_nothing_failed(tmp_path: Path) -> None:
    run_dir = fake_run(tmp_path / "runs", "r")
    summary_path, report_path = write_report(run_dir, load_scenarios(SMOKE), tmp_path / "out")
    text = report_path.read_text(encoding="utf-8")
    assert "> Every scenario in this run is hand-authored" in text
    assert "_No failed items._" in text and "_No reply text on the failed items._" in text
    assert summary_path.name == "summary.json"


def test_report_refuses_stale_trace_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = fake_run(tmp_path / "runs", "r")
    make_v0(run_dir)
    with pytest.raises(StaleScoresError, match="afandem score"):
        load_items(run_dir)
    capsys.readouterr()
    args = ["report", str(run_dir), "--scenarios", str(SMOKE), "--results-dir", str(tmp_path)]
    assert main(args) == 2
    assert "run `afandem score" in capsys.readouterr().err
    assert main(["score", str(run_dir), "--scenarios", str(SMOKE)]) == 0
    assert main(args) == 0
    assert main(["report", str(tmp_path / "missing")]) == 2


def test_markdown_helpers() -> None:
    assert table(["a", "b"], [["x|y", None]]) == "| a | b |\n| --- | ---: |\n| x\\|y | - |"
    rendered = render(
        {
            "run": {"run_id": "x", "parameters": []},
            "columns": [],
            "generated_by": {
                "scorer_version": "1.0",
                "normaliser_version": "1",
                "scores_from": "t",
            },
            "behaviours": {},
            "drafts": {"draft_scenarios": 0, "items": 0},
            "task_success": {
                k: {} for k in ("primary", "inform", "harmful", "out_of_scope", "all")
            },
            "gaps_primary": {},
            "metrics": {},
            "validity": {},
            "flags": {},
            "turn1_labels": {},
            "exclusions": {},
            "failures": [],
        }
    )
    assert "_No items._" in rendered and "_No run.json targets._" in rendered


def test_is_draft_reads_every_text(tmp_path: Path) -> None:
    (scenario,) = [s.scenario for s in load_scenarios(SMOKE) if s.scenario.id == "clinic-9001"]
    assert is_draft(scenario) is False
    data: dict[str, Any] = scenario.model_dump(mode="json", by_alias=True)
    data["arabizi_variant"] = {"text": "[v]", "profile": "variant", "provenance": "assistant_draft"}
    assert is_draft(type(scenario).model_validate(data)) is True


def test_validity_and_flags_render_as_rates(tmp_path: Path) -> None:
    run_dir = fake_run(
        tmp_path / "runs",
        "r",
        overrides={"banking-9001|egy": "invented_tool", "clinic-9001|egy": "length_mid_call"},
    )
    summary = build_summary(run_dir, load_scenarios(SMOKE))
    assert summary["validity"]["fake"]["egy"]["items_scored"] == 9
    assert summary["flags"]["fake"]["egy"]["items"] == 9
    text = render(summary)
    assert "| fake | egy | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 2/9 (22%) |" in text
    assert "| fake | egy | 1/9 (11%) | 0/9 | 0/9 | 1/9 (11%) |" in text


def test_share_formatting() -> None:
    assert (_share(0, 0), _share(0, 4), _share(1, 4)) == ("-", "0/4", "1/4 (25%)")
