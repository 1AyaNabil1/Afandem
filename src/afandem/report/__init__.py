"""Descriptive reports: `afandem report RUN_DIR` -> `results/<run_id>/summary.json` + `report.md`.

Phase 1 is descriptive only (no bootstrap CIs or McNemar; those are `report/stats.py`, Phase 3).
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from afandem.report.markdown import render
from afandem.report.summary import StaleScoresError, build_summary
from afandem.scenarios import LoadedScenario

SUMMARY_FILE: Final = "summary.json"
REPORT_FILE: Final = "report.md"


def write_report(
    run_dir: Path, scenarios: Sequence[LoadedScenario], results_dir: Path
) -> tuple[Path, Path]:
    """Write `<results_dir>/<run_id>/summary.json` and `report.md`; returns both paths."""
    summary = build_summary(run_dir, scenarios)
    out = results_dir / str(summary["run"]["run_id"])
    out.mkdir(parents=True, exist_ok=True)
    summary_path, report_path = out / SUMMARY_FILE, out / REPORT_FILE
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path.write_text(render(summary), encoding="utf-8")
    return summary_path, report_path


__all__ = [
    "REPORT_FILE",
    "SUMMARY_FILE",
    "StaleScoresError",
    "build_summary",
    "render",
    "write_report",
]
