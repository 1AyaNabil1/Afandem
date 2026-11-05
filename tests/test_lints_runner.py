"""The lint runner, cross-file lints and `afandem data lint`. Texts are the spec example or
`<column text>` placeholders."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.cli import main
from afandem.lints import SCENARIO_RULES, lint_document, lint_path, lint_scenario
from afandem.scenarios import COLUMNS, Scenario

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
FIXTURE = FIXTURES / "clinic" / "clinic-0042.json"
OTHER_GUID = "11111111-1111-4111-8111-111111111111"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def write(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def refuse_twin(scenario_id: str) -> dict[str, Any]:
    doc = example()
    doc["id"] = scenario_id
    doc["behaviour"] = "refuse"
    doc["harm_type"] = "explicit_mismatch"
    doc["expected"]["tool_calls"] = []
    doc["expected"]["end_state_patch"] = {}
    for name in COLUMNS:
        doc["texts"][name]["confirm_yes"] = None
    return doc


def test_lint_document_on_the_spec_example() -> None:
    findings, scenario = lint_document(example())
    assert scenario is not None
    assert scenario.id == "clinic-0042"
    assert {f.severity for f in findings} == {"manual"}


def test_lint_document_reports_schema_and_provenance() -> None:
    doc = example()
    doc["texts"]["egy"]["provenance"] = "llm"
    doc["texts"]["msa"]["natural"] = 0
    findings, scenario = lint_document(doc)
    assert scenario is None
    assert [(f.rule, f.column, f.field) for f in findings] == [
        ("provenance", "egy", "provenance"),
        ("schema", "msa", "natural"),
        ("schema", "egy", "provenance"),
    ]


def test_cross_field_schema_errors_are_scenario_level() -> None:
    doc = example()
    doc["harm_type"] = "explicit_mismatch"
    findings, _ = lint_document(doc)
    assert [(f.rule, f.column) for f in findings] == [("schema", None)]
    assert "harm_type" in findings[0].message


def test_every_rule_reports_under_its_own_id() -> None:
    doc = example()
    for name in COLUMNS:
        doc["texts"][name]["text"] = f"<{name} text>"
        doc["texts"][name]["confirm_yes"] = f"<{name} confirm>"
    doc["texts"]["egy"]["phenomena"].append("letter_variants")
    doc["texts"]["en"]["text"] = "<en text> ambulance"  # a forbidden-topic lexicon term
    doc["tools"].remove("list_doctors")
    doc["slots"]["new_date_weekday"] = "Monday"
    doc["initial_state"]["calendar"]["holidays"].append("2026-11-08")  # the gold's date
    findings = lint_scenario(Scenario.model_validate(doc))
    emitted = {f.rule for f in findings}
    assert emitted <= {*SCENARIO_RULES, "canary"}
    assert {
        "slot_reextraction",
        "slot_dates",
        "calendar",
        "egyptian_marker",
        "cs_insertions",
        "follow_up_lexicon",
        "harmful_text",
        "orthographic_tags",
        "noise_subset",
        "tool_set",
        "solvability",
    } <= emitted


def test_lint_path_on_a_tree(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", example())
    report = lint_path(tmp_path)
    assert report.files == [tmp_path / "clinic" / "clinic-0042.json"]
    assert report.ok
    assert report.count("manual") == 2
    assert all(f.path == report.files[0] for f in report.findings)
    assert all(f.scenario_id == "clinic-0042" for f in report.findings)


def test_lint_path_keeps_going_after_a_broken_file(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", example())
    broken = tmp_path / "clinic" / "clinic-0043.json"
    broken.write_text("{", encoding="utf-8")
    report = lint_path(tmp_path)
    assert not report.ok
    assert [(f.rule, f.path) for f in report.findings if f.severity == "error"] == [
        ("load", broken)
    ]


def test_corpus_duplicate_ids_and_layout(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", example())
    write(tmp_path / "clinic" / "copy.json", example())
    banking = example()
    banking["id"] = "clinic-0044"
    write(tmp_path / "banking" / "clinic-0044.json", banking)
    report = lint_path(tmp_path)
    errors = {(f.rule, f.path.name) for f in report.findings if f.severity == "error" and f.path}
    assert errors == {
        ("duplicate_id", "copy.json"),
        ("layout", "copy.json"),
        ("layout", "clinic-0044.json"),
    }


@pytest.mark.parametrize(
    ("twin", "expected"),
    [
        ("refuse", []),
        ("act", [("control_of", "error")]),
        (None, [("control_of", "warning")]),
    ],
)
def test_corpus_control_twins(
    tmp_path: Path, twin: str | None, expected: list[tuple[str, str]]
) -> None:
    control = example()
    control["control_of"] = "clinic-0050"
    write(tmp_path / "clinic" / "clinic-0042.json", control)
    if twin == "refuse":
        write(tmp_path / "clinic" / "clinic-0050.json", refuse_twin("clinic-0050"))
    elif twin == "act":
        other = example()
        other["id"] = "clinic-0050"
        write(tmp_path / "clinic" / "clinic-0050.json", other)
    report = lint_path(tmp_path)
    found = [(f.rule, f.severity) for f in report.findings if f.rule == "control_of"]
    assert found == expected


def test_corpus_has_one_canary_guid(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", example())
    other = example()
    other["id"] = "clinic-0043"
    other["canary"] = other["canary"].rsplit(" ", 1)[0] + " " + OTHER_GUID
    write(tmp_path / "clinic" / "clinic-0043.json", other)
    report = lint_path(tmp_path)
    assert [f.rule for f in report.findings if f.severity == "error"] == ["canary"]
    assert lint_path(tmp_path, canary_guid=OTHER_GUID).count("error") == 2


def test_cli_data_lint_clean(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "lint", str(FIXTURES)]) == 0
    out = capsys.readouterr().out
    assert "1 file(s): 0 error(s), 0 warning(s), 2 manual check(s)" in out
    assert "--manual lists them" in out
    assert "slot 'intent'" not in out


def test_cli_data_lint_manual(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "lint", str(FIXTURE), "--manual"]) == 0
    out = capsys.readouterr().out
    assert "manual [slot_reextraction] scenario: slot 'intent'" in out


def test_cli_data_lint_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = example()
    doc["texts"]["egy"]["text"] = "<egy text>"
    path = write(tmp_path / "clinic" / "clinic-0042.json", doc)
    assert main(["data", "lint", str(path)]) == 1
    out = capsys.readouterr().out
    assert f"{path}: error [egyptian_marker] egy.text:" in out


def drafted(*columns: str) -> dict[str, Any]:
    doc = example()
    for name in columns:
        doc["texts"][name]["provenance"] = "assistant_draft"
    return doc


def test_lint_path_allow_drafts(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", drafted("egy", "en"))
    strict = lint_path(tmp_path)
    assert not strict.ok
    assert [(f.rule, f.column) for f in strict.findings if f.severity == "error"] == [
        ("provenance", "en"),
        ("provenance", "egy"),
    ]
    lenient = lint_path(tmp_path, allow_drafts=True)
    assert lenient.ok
    assert lenient.count("warning") == 2


def test_cli_data_lint_drafts_fail_without_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path / "clinic" / "clinic-0042.json", drafted("egy"))
    assert main(["data", "lint", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert f"{path}: error [provenance] egy.provenance: drafted by the AI assistant" in out
    assert "1 file(s): 1 error(s), 0 warning(s)" in out
    assert "--allow-drafts" not in out


def test_cli_data_lint_allow_drafts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path / "clinic" / "clinic-0042.json", drafted("egy", "cs_latin"))
    assert main(["data", "lint", str(tmp_path), "--allow-drafts"]) == 0
    out = capsys.readouterr().out
    assert f"{path}: warning [provenance] egy.provenance: drafted by the AI assistant" in out
    assert f"{path}: warning [provenance] cs_latin.provenance:" in out
    assert "1 file(s): 0 error(s), 2 warning(s)" in out
    assert "2 assistant_draft finding(s) reported as warnings (--allow-drafts)" in out


def test_cli_data_lint_allow_drafts_keeps_other_provenance_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = drafted("egy")
    doc["texts"]["msa"]["provenance"] = "llm"
    path = write(tmp_path / "clinic" / "clinic-0042.json", doc)
    assert main(["data", "lint", str(path), "--allow-drafts"]) == 1
    out = capsys.readouterr().out
    assert f"{path}: warning [provenance] egy.provenance:" in out
    assert f"{path}: error [provenance] msa.provenance: provenance is 'llm'" in out


def test_cli_data_lint_bad_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "lint", str(tmp_path / "nope")]) == 2
    assert "no such file or directory" in capsys.readouterr().err


def test_cli_run_fake_still_works(tmp_path: Path) -> None:
    smoke = Path(__file__).parent / "fixtures" / "smoke"
    args = ["run", "--fake", "--scenarios", str(smoke), "--runs-dir", str(tmp_path)]
    assert main([*args, "--columns", "en"]) == 0
