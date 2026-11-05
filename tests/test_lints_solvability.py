"""The solvability lint: the discovering oracle run from `afandem data lint`. Scenarios are the spec
example and the smoke fixtures (placeholder texts); the oracle never reads the texts."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.lints import Finding, check_solvability, lint_path
from afandem.providers import discover
from afandem.scenarios import COLUMNS, Scenario

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "tests" / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"
SMOKE = ROOT / "tests" / "fixtures" / "smoke"


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def lint(doc: dict[str, Any]) -> list[Finding]:
    return check_solvability(Scenario.model_validate(doc))


def test_the_spec_example_and_the_banking_transfer_are_solvable() -> None:
    assert lint(load(EXAMPLE)) == []
    assert lint(load(SMOKE / "banking" / "banking-9001.json")) == []


def test_every_scenario_in_data_and_the_fixtures_is_solvable() -> None:
    for root in (ROOT / "data", SMOKE, EXAMPLE.parent.parent):
        report = lint_path(root, allow_drafts=True)
        assert [f for f in report.findings if f.rule == "solvability"] == [], root


def test_an_unsolvable_item_is_an_error_naming_the_reasons_and_calls() -> None:
    doc = load(EXAMPLE)
    doc["slots"]["new_time"] = "16:00"  # the slot table no longer means the gold
    (finding,) = lint(doc)
    assert (finding.rule, finding.severity, finding.column) == ("solvability", "error", None)
    assert "did not solve it: state: " in finding.message
    assert "(calls: get_appointments, reschedule_appointment)" in finding.message


def test_an_inform_answer_no_tool_returns_is_an_error() -> None:
    doc = load(SMOKE / "banking" / "banking-9002.json")
    doc["expected"]["answer_must_contain"] = [{"value": 999, "forms": ["999"]}]
    (finding,) = lint(doc)
    assert "did not solve it: answer_missing (calls: get_balance)" in finding.message


def test_a_gold_that_cannot_be_prepared() -> None:
    doc = load(EXAMPLE)
    doc["expected"]["end_state_patch"]["appointments[a_9]"]["date"] = "2026-11-09"
    (finding,) = lint(doc)
    assert (finding.field, finding.severity) == ("expected", "error")
    assert finding.message.startswith("the expected end state cannot be prepared: ")


def test_behaviours_without_a_task_for_the_oracle_are_not_run() -> None:
    doc = load(EXAMPLE)
    doc["slots"]["new_time"] = "16:00"
    doc["behaviour"] = "refuse"
    doc["harm_type"] = "inferable_mismatch"
    doc["expected"].update(tool_calls=[], end_state_patch={})
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
    assert lint(doc) == []


def test_a_state_that_does_not_load_is_left_to_the_state_lint() -> None:
    doc = load(EXAMPLE)
    doc["initial_state"]["calendar"] = {}
    assert lint(doc) == []


def test_a_domain_without_a_sandbox_is_skipped() -> None:
    scenario = Scenario.model_validate(load(EXAMPLE))
    assert check_solvability(scenario.model_copy(update={"domain": "telecom"})) == []


def test_an_oracle_failure_is_a_finding_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: object, **__: object) -> Any:
        raise KeyError("date")

    monkeypatch.setattr(discover, "solve", broken)
    (finding,) = lint(load(EXAMPLE))
    assert finding.message == "the discovering oracle failed: KeyError: 'date'"


async def test_the_lint_also_runs_inside_an_event_loop() -> None:
    doc = load(EXAMPLE)
    doc["slots"]["new_time"] = "16:00"
    assert [f.rule for f in lint(doc)] == ["solvability"]
