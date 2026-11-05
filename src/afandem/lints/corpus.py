"""Lints across scenario files: unique ids, control twins, one canary GUID, file layout."""

from collections.abc import Sequence

from afandem.lints.findings import Finding
from afandem.lints.structure import canary_guid
from afandem.scenarios.loader import LoadedScenario
from afandem.scenarios.schema import DOMAINS


def _at(item: LoadedScenario, finding: Finding) -> Finding:
    return finding.located(path=item.path, scenario_id=item.scenario.id)


def check_corpus(loaded: Sequence[LoadedScenario]) -> list[Finding]:
    findings: list[Finding] = []
    by_id: dict[str, LoadedScenario] = {}
    for item in loaded:
        scenario = item.scenario
        first = by_id.setdefault(scenario.id, item)
        if first is not item:
            message = f"duplicate id {scenario.id!r} (also {first.path})"
            findings.append(_at(item, Finding("duplicate_id", message)))
        if item.path.stem != scenario.id:
            message = f"file name {item.path.name!r} does not match id {scenario.id!r}"
            findings.append(_at(item, Finding("layout", message)))
        parent = item.path.parent.name
        if parent in DOMAINS and parent != scenario.domain:
            message = f"a {scenario.domain} scenario sits in {parent}/"
            findings.append(_at(item, Finding("layout", message)))
    for item in loaded:
        target_id = item.scenario.control_of
        if target_id is None:
            continue
        target = by_id.get(target_id)
        if target is None:
            message = f"control_of {target_id!r} is not among the linted scenarios"
            findings.append(_at(item, Finding("control_of", message, severity="warning")))
        elif target.scenario.behaviour != "refuse":
            message = f"control_of {target_id!r} is a {target.scenario.behaviour} item, not refuse"
            findings.append(_at(item, Finding("control_of", message)))
    guids: dict[str, list[str]] = {}
    for item in loaded:
        guid = canary_guid(item.scenario.canary)
        if guid is not None:
            guids.setdefault(guid, []).append(item.scenario.id)
    if len(guids) > 1:
        detail = "; ".join(f"{guid}: {', '.join(ids)}" for guid, ids in sorted(guids.items()))
        findings.append(Finding("canary", f"more than one canary GUID in the corpus ({detail})"))
    return findings
