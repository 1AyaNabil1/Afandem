"""Run every lint on a document, a scenario, a file or a tree of files."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from afandem.lints.arabizi import check_arabizi_profile
from afandem.lints.calendar import check_calendar
from afandem.lints.codeswitch import check_cs_insertions
from afandem.lints.corpus import check_corpus
from afandem.lints.egyptian import (
    check_diacritics,
    check_egyptian_markers,
    check_gender,
    check_msa_isms,
    check_msa_syntax,
)
from afandem.lints.findings import Finding
from afandem.lints.followup import check_follow_up_lexicon
from afandem.lints.harmful import check_harmful_text
from afandem.lints.slots import check_slot_dates, check_slots
from afandem.lints.solvability import check_solvability
from afandem.lints.state import check_state
from afandem.lints.structure import (
    check_canary,
    check_length_ratio,
    check_noise_subset,
    check_orthographic_tags,
    check_phenomenon_realised,
    check_provenance,
    check_tool_set,
)
from afandem.scenarios.loader import (
    LoadedScenario,
    ScenarioLoadError,
    format_location,
    read_document,
    scenario_paths,
    scenario_sha256,
)
from afandem.scenarios.schema import COLUMNS, Scenario

ScenarioRule = Callable[[Scenario], list[Finding]]

SCENARIO_RULES: Mapping[str, ScenarioRule] = {
    "slot_reextraction": check_slots,
    "slot_dates": check_slot_dates,
    "calendar": check_calendar,
    "length_ratio": check_length_ratio,
    "egyptian_marker": check_egyptian_markers,
    "msa_ism": check_msa_isms,
    "msa_egyptian_syntax": check_msa_syntax,
    "diacritics": check_diacritics,
    "arabizi_profile": check_arabizi_profile,
    "cs_insertions": check_cs_insertions,
    "gender": check_gender,
    "follow_up_lexicon": check_follow_up_lexicon,
    "harmful_text": check_harmful_text,
    "phenomenon_realised": check_phenomenon_realised,
    "orthographic_tags": check_orthographic_tags,
    "noise_subset": check_noise_subset,
    "tool_set": check_tool_set,
    "state": check_state,
    "solvability": check_solvability,
}
"""Per-scenario rules in report order; `canary` (which takes the project GUID) runs after."""


def lint_scenario(scenario: Scenario, *, canary_guid: str | None = None) -> list[Finding]:
    """Every per-scenario lint on a validated scenario."""
    findings: list[Finding] = []
    for rule in SCENARIO_RULES.values():
        findings.extend(rule(scenario))
    findings.extend(check_canary(scenario, canary_guid))
    return findings


def schema_findings(exc: ValidationError) -> list[Finding]:
    """One `schema` finding per pydantic error, located at its column when there is one."""
    findings: list[Finding] = []
    for error in exc.errors():
        loc = tuple(error["loc"])
        column = str(loc[1]) if len(loc) > 1 and loc[0] == "texts" and loc[1] in COLUMNS else None
        field_name = str(loc[2]) if column is not None and len(loc) > 2 else None
        message = f"{format_location(loc)}: {error['msg']}"
        findings.append(Finding("schema", message, column=column, field=field_name))
    return findings


def lint_document(
    document: Mapping[str, Any], *, canary_guid: str | None = None, allow_drafts: bool = False
) -> tuple[list[Finding], Scenario | None]:
    """Provenance and schema checks on a parsed document, then every per-scenario lint.

    `allow_drafts` reports `assistant_draft` provenance as a warning instead of an error.
    """
    findings = check_provenance(document, allow_drafts=allow_drafts)
    try:
        scenario = Scenario.model_validate(document)
    except ValidationError as exc:
        return findings + schema_findings(exc), None
    return findings + lint_scenario(scenario, canary_guid=canary_guid), scenario


@dataclass(slots=True)
class LintReport:
    files: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def count(self, severity: str) -> int:
        return sum(1 for finding in self.findings if finding.severity == severity)

    @property
    def ok(self) -> bool:
        """No errors (warnings and manual checks do not fail a lint run)."""
        return self.count("error") == 0


def lint_paths(
    paths: Sequence[Path], *, canary_guid: str | None = None, allow_drafts: bool = False
) -> LintReport:
    report = LintReport(files=list(paths))
    loaded: list[LoadedScenario] = []
    for path in paths:
        try:
            document = read_document(path)
        except ScenarioLoadError as exc:
            report.findings.append(Finding("load", exc.message, path=path))
            continue
        findings, scenario = lint_document(
            document, canary_guid=canary_guid, allow_drafts=allow_drafts
        )
        scenario_id = scenario.id if scenario is not None else _document_id(document)
        report.findings.extend(f.located(path=path, scenario_id=scenario_id) for f in findings)
        if scenario is not None:
            loaded.append(LoadedScenario(path, document, scenario, scenario_sha256(document)))
    report.findings.extend(check_corpus(loaded))
    return report


def lint_path(
    path: str | Path, *, canary_guid: str | None = None, allow_drafts: bool = False
) -> LintReport:
    """Lint one file, a domain directory, or a tree of `<domain>/*.json` directories."""
    return lint_paths(scenario_paths(path), canary_guid=canary_guid, allow_drafts=allow_drafts)


def _document_id(document: Mapping[str, Any]) -> str | None:
    value = document.get("id")
    return value if isinstance(value, str) else None
