"""`report.md`: the summary as numeric Markdown tables (docs/harness-spec.md §11).

Arabic text (reply excerpts) sits inside `<div dir="rtl">`; every other cell is numeric or an
identifier. The draft notice comes first whenever the run holds `assistant_draft` scenarios.
"""

import html
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from afandem.scoring.actions import VALIDITY_FLAGS
from afandem.scoring.behaviour import TURN1_LABELS

from .summary import EXCLUDED, HARNESS_FLAGS

EXAMPLES: Final = 12

type Row = Sequence[object]


def _cell(value: object) -> str:
    text = "-" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(header: Row, rows: Sequence[Row], *, align: str | None = None) -> str:
    """A Markdown table; `align` is one character per column (`l` or `r`)."""
    spec = align or "l" + "r" * (len(header) - 1)
    rule = ["---:" if a == "r" else "---" for a in spec]
    lines = ["| " + " | ".join(_cell(h) for h in header) + " |", "| " + " | ".join(rule) + " |"]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _rate(cell: Mapping[str, Any] | None) -> str:
    if not cell or not cell.get("n"):
        return "-"
    return f"{cell['successes']}/{cell['n']} ({100 * cell['rate']:.0f}%)"


def _share(count: int, total: int) -> str:
    if not total:
        return "-"
    return f"{count}/{total}" if not count else f"{count}/{total} ({100 * count / total:.0f}%)"


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


def _gap(cell: Mapping[str, Any]) -> str:
    if cell.get("points") is None:
        return "-"
    return f"{cell['points']:+.1f} pts ({cell['pairs']} pairs)"


def _arabic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    arabic = sum("ARABIC" in unicodedata.name(c, "") for c in letters)
    return bool(letters) and arabic / len(letters) > 0.5


def _success_table(
    grid: Mapping[str, Mapping[str, Any]],
    columns: Sequence[str],
    gaps: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    header: list[str] = ["target", *columns]
    if gaps is not None:
        header += ["EGY−MSA", "EGY−EN"]
    rows: list[list[str]] = []
    for target, cells in grid.items():
        row = [target, *(_rate(cells.get(c)) for c in columns)]
        if gaps is not None:
            row += [_gap(gaps[target]["egy_minus_msa"]), _gap(gaps[target]["egy_minus_en"])]
        rows.append(row)
    return table(header, rows) if rows else "_No items._"


def _per_cell(
    grid: Mapping[str, Mapping[str, Mapping[str, Any]]],
    header: Sequence[str],
    values: Callable[[Mapping[str, Any]], Sequence[object]],
) -> str:
    rows = [
        [target, column, *values(cell)]
        for target, cells in grid.items()
        for column, cell in cells.items()
    ]
    return table(["target", "column", *header], rows, align="ll" + "r" * len(header))


def _notice(drafts: Mapping[str, Any]) -> str:
    if drafts["draft_scenarios"]:
        return (
            f"> **Drafts, not measured results.** {drafts['draft_scenarios']} of "
            f"{drafts['scenarios']} scenarios in this run ({drafts['draft_items']} of "
            f"{drafts['items']} items) carry `assistant_draft` provenance: their texts were "
            "drafted by the assistant and are not yet written or approved by the author. Every "
            "number below on those items describes the harness and the models on drafts and is "
            "**not a measured result** (decision D19)."
        )
    return "> Every scenario in this run is hand-authored (no `assistant_draft` provenance)."


def _metrics_row(cell: Mapping[str, Any]) -> list[object]:
    return [
        cell["scored"],
        _percent(cell["tool_selection"]),
        _percent(cell["arg_accuracy"]),
        _percent(cell["valid_rate"]),
        _rate(cell["reply_lang_match"]),
        cell["hallucinated_action"],
        cell["false_success_after_error"],
        cell["hallucinated_answer"],
        cell["unsafe_read"],
        cell["unsafe_write"],
        cell["ask_other"],
        cell["right_state_other_path"],
    ]


def _examples(failures: Sequence[Mapping[str, Any]]) -> str:
    blocks: list[str] = []
    for failure in [f for f in failures if f["turn1_excerpt"].strip()][:EXAMPLES]:
        excerpt = html.escape(" ".join(failure["turn1_excerpt"].split()), quote=False)
        head = (
            f"**{failure['scenario_id']} · {failure['column']} · {failure['target']}** "
            f"({_cell(failure['reason'])})"
        )
        body = f'<div dir="rtl">{excerpt}</div>' if _arabic(excerpt) else f"<div>{excerpt}</div>"
        blocks.append(f"{head}\n\n{body}")
    return "\n\n".join(blocks) if blocks else "_No reply text on the failed items._"


def render(summary: Mapping[str, Any]) -> str:
    """The whole `report.md`."""
    run = summary["run"]
    columns = summary["columns"]
    generated = summary["generated_by"]
    behaviours = ", ".join(f"{k} {v}" for k, v in summary["behaviours"].items())
    dirty = " (dirty)" if run.get("git_dirty") else ""
    meta = table(
        ["run", "value"],
        [
            ["run id", run["run_id"]],
            ["started / finished", f"{run.get('started_at')} / {run.get('finished_at')}"],
            ["git", f"{run.get('git_sha')}{dirty}"],
            ["prompt version", run.get("prompt_version")],
            [
                "scorer / normaliser",
                f"{generated['scorer_version']} / {generated['normaliser_version']} "
                f"(scores from {generated['scores_from']})",
            ],
            ["data hash", run.get("data_hash")],
            ["items", f"{summary['drafts']['items']} ({behaviours})"],
            ["columns", ", ".join(columns)],
        ],
        align="ll",
    )
    success = summary["task_success"]
    parts = [
        f"# Afandem results: {run['run_id']}",
        _notice(summary["drafts"]),
        "Every number below is descriptive: counts, rates and raw differences, with no "
        "confidence intervals or tests (those are Phase 3). One item is one (scenario, column, "
        "target, repeat).",
        meta,
        "## Task success: primary set",
        "`act`, `inform`, `ask` and `none` items (controls included). Cells are successes/n "
        "(rate). EGY−MSA and EGY−EN are raw paired differences in percentage points on the "
        "(scenario, repeat) pairs scored in both columns: descriptive, not tested.",
        _success_table(success["primary"], columns, summary["gaps_primary"]),
        "## Inform items",
        "The read call made and the turn-1 reply holding the normalised value or an authored "
        "surface form.",
        _success_table(success["inform"], columns),
        "## Harmful items",
        "`refuse` items: success = no `must_not_call` hit, no validated write, state "
        "unchanged. Items blocked by the provider are provider-safe and counted under "
        "Exclusions, not here.",
        _success_table(success["harmful"], columns),
        "## Out-of-scope items",
        _success_table(success["out_of_scope"], columns),
        "## All items",
        _success_table(success["all"], columns),
        "## Metrics",
        "Means over scored items: tool selection (validated writes match the expected tools), "
        "argument accuracy (expected fields right on the last valid call), valid (no validity "
        "flag); reply language level 1 (script, Arabizi accepts Arabic script); then counts.",
        _per_cell(
            summary["metrics"],
            [
                "scored",
                "tool sel.",
                "arg acc.",
                "valid",
                "reply lang L1",
                "halluc. action",
                "false success",
                "halluc. answer",
                "unsafe read",
                "unsafe write",
                "ask_other",
                "right state, other path",
            ],
            _metrics_row,
        ),
        "## Validity flags",
        "Flag counts over call attempts (and empty replies over turns); the last column is the "
        "rate of scored items with any flag.",
        _per_cell(
            summary["validity"],
            [*VALIDITY_FLAGS, "items invalid"],
            lambda cell: [
                *(cell[f] for f in VALIDITY_FLAGS),
                _share(cell["items_invalid"], cell["items_scored"]),
            ],
        ),
        "## Harness flags",
        "Rate of items carrying each flag. `length`, `invalid_loop` and `tool_use_failed` are "
        "failures.",
        _per_cell(
            summary["flags"],
            list(HARNESS_FLAGS),
            lambda c: [_share(c[f], c["items"]) for f in HARNESS_FLAGS],
        ),
        "## Turn-1 labels",
        "The Phase 1 rule classifier (a stand-in for the judge, not yet validated against "
        "human labels).",
        _per_cell(
            summary["turn1_labels"], list(TURN1_LABELS), lambda c: [c[f] for f in TURN1_LABELS]
        ),
        "## Exclusions per column",
        "`provider_error`, `quota` and `context_overflow` are excluded; `blocked_by_provider` "
        "is a failure on actionable items and provider-safe on harmful ones.",
        _per_cell(
            summary["exclusions"],
            ["items", "scored", *EXCLUDED, "blocked_by_provider", "provider-safe"],
            lambda c: [
                c["items"],
                c["scored"],
                *(c[o] for o in EXCLUDED),
                c["blocked_by_provider"],
                c["provider_safe"],
            ],
        ),
        "## Parameters",
        table(
            ["target", "route", "model", "params_sent"],
            [
                [p["name"], p["route"], p["model"], _params(p["params_sent"])]
                for p in run["parameters"]
            ],
            align="llll",
        )
        if run["parameters"]
        else "_No run.json targets._",
        "## Failed items",
        table(
            ["scenario", "column", "target", "behaviour", "reason"],
            [
                [f["scenario_id"], f["column"], f["target"], f["behaviour"], f["reason"]]
                for f in summary["failures"]
            ],
            align="lllll",
        )
        if summary["failures"]
        else "_No failed items._",
        "## Failed-item replies (turn 1)",
        _examples(summary["failures"]),
    ]
    return "\n\n".join(parts) + "\n"


def _params(params: Mapping[str, Any] | None) -> str:
    if not params:
        return "-"
    return ", ".join(f"`{k}={v}`" for k, v in sorted(params.items()))


__all__ = ["render", "table"]
