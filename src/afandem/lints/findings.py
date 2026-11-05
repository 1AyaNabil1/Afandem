"""The finding type every lint returns."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning", "manual"]
"""`error` breaks a spec rule; `warning` is a heuristic hit to look at; `manual` marks a
check the lint cannot decide mechanically (the author re-extracts or reads it)."""


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    message: str
    column: str | None = None
    field: str | None = None
    severity: Severity = "error"
    scenario_id: str | None = None
    path: Path | None = None

    def located(self, *, path: Path | None, scenario_id: str | None) -> "Finding":
        """A copy carrying the file and scenario it came from."""
        return replace(
            self,
            path=self.path if path is None else path,
            scenario_id=self.scenario_id if scenario_id is None else scenario_id,
        )

    @property
    def where(self) -> str:
        """`column.field`, `column`, or `scenario` for scenario-level findings."""
        if self.column is None:
            return "scenario" if self.field is None else self.field
        return self.column if self.field is None else f"{self.column}.{self.field}"

    def __str__(self) -> str:
        prefix = f"{self.path}: " if self.path is not None else ""
        return f"{prefix}{self.severity} [{self.rule}] {self.where}: {self.message}"
