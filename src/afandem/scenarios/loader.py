"""Load scenario files: one file, a domain directory, or the `data/` tree.

Files are strict UTF-8 JSON objects (no duplicate keys, no NaN). Every error names the file.
`scenario_sha256` hashes the canonical JSON of the parsed document (sorted keys,
`ensure_ascii=False`, no insignificant whitespace), so key order and indentation never
change it while any edit to a value does.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from afandem.scenarios.schema import DOMAINS, Scenario


class ScenarioLoadError(Exception):
    """A scenario file could not be read, parsed or validated."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True, slots=True)
class LoadedScenario:
    path: Path
    document: dict[str, Any]
    scenario: Scenario
    sha256: str


def canonical_json(document: Mapping[str, Any]) -> str:
    """The canonical serialisation hashed by `scenario_sha256`."""
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def scenario_sha256(document: Mapping[str, Any]) -> str:
    """SHA-256 (hex) of the canonical JSON of a parsed scenario document."""
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def read_document(path: str | Path) -> dict[str, Any]:
    """Read one file as a strict UTF-8 JSON object."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ScenarioLoadError(path, f"cannot read file ({exc.strerror})") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScenarioLoadError(path, f"not valid UTF-8 (byte {exc.start})") from exc
    try:
        data = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ScenarioLoadError(
            path, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except ValueError as exc:
        raise ScenarioLoadError(path, f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ScenarioLoadError(path, "a scenario file must hold one JSON object")
    return data


def format_location(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in loc) or "<scenario>"


def format_validation_error(exc: ValidationError) -> str:
    """One line per pydantic error: `location: message`."""
    return "; ".join(
        f"{format_location(tuple(error['loc']))}: {error['msg']}" for error in exc.errors()
    )


def validate_document(document: Mapping[str, Any], path: Path) -> Scenario:
    try:
        return Scenario.model_validate(document)
    except ValidationError as exc:
        raise ScenarioLoadError(path, format_validation_error(exc)) from exc


def load_scenario(path: str | Path) -> LoadedScenario:
    """Read, validate and hash one scenario file."""
    path = Path(path)
    document = read_document(path)
    scenario = validate_document(document, path)
    return LoadedScenario(
        path=path, document=document, scenario=scenario, sha256=scenario_sha256(document)
    )


def scenario_paths(path: str | Path) -> list[Path]:
    """The scenario files under `path`, sorted.

    A file is returned as is; a directory named after a domain yields its `*.json`; any
    other directory yields `<dir>/<domain>/*.json` for each domain directory it contains
    (so `data/schema/` and other side folders are never read as scenarios).
    """
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ScenarioLoadError(path, "no such file or directory")
    if path.name in DOMAINS:
        return sorted(path.glob("*.json"))
    domain_dirs = [path / domain for domain in DOMAINS if (path / domain).is_dir()]
    if not domain_dirs:
        raise ScenarioLoadError(
            path, f"no domain directories ({', '.join(DOMAINS)}) and not a domain directory"
        )
    return sorted(file for directory in domain_dirs for file in directory.glob("*.json"))


def load_scenarios(path: str | Path) -> list[LoadedScenario]:
    """Load every scenario under `path` (see `scenario_paths`); ids must be unique."""
    loaded = [load_scenario(file) for file in scenario_paths(path)]
    seen: dict[str, Path] = {}
    for item in loaded:
        first = seen.setdefault(item.scenario.id, item.path)
        if first != item.path:
            raise ScenarioLoadError(item.path, f"duplicate id {item.scenario.id!r} (also {first})")
    return loaded
