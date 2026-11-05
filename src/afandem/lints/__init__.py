"""Data lints for scenario files (docs/dataset-spec.md §2, lint table).

Every lint is a pure function returning `Finding`s (rule id, column, field, message,
severity). `lint_path` runs them all over files on disk; `afandem data lint <path>` prints
the result.
"""

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
from afandem.lints.findings import Finding, Severity
from afandem.lints.followup import check_follow_up_lexicon
from afandem.lints.runner import (
    SCENARIO_RULES,
    LintReport,
    lint_document,
    lint_path,
    lint_paths,
    lint_scenario,
)
from afandem.lints.slots import check_slot_dates, check_slots
from afandem.lints.structure import (
    check_canary,
    check_length_ratio,
    check_noise_subset,
    check_orthographic_tags,
    check_phenomenon_realised,
    check_provenance,
    check_tool_set,
)

__all__ = [
    "SCENARIO_RULES",
    "Finding",
    "LintReport",
    "Severity",
    "check_arabizi_profile",
    "check_calendar",
    "check_canary",
    "check_corpus",
    "check_cs_insertions",
    "check_diacritics",
    "check_egyptian_markers",
    "check_follow_up_lexicon",
    "check_gender",
    "check_length_ratio",
    "check_msa_isms",
    "check_msa_syntax",
    "check_noise_subset",
    "check_orthographic_tags",
    "check_phenomenon_realised",
    "check_provenance",
    "check_slot_dates",
    "check_slots",
    "check_tool_set",
    "lint_document",
    "lint_path",
    "lint_paths",
    "lint_scenario",
]
