"""Render scenarios as one Markdown review sheet for the author (all six columns per item).

    uv run python scripts/review_sheet.py data --out "<path>/Scenario review.md"

For each scenario: behaviour, `now`, speaker, register and tags; what a correct agent does
(the expected calls, the reads and answer for `inform`, the clarification slot for `ask`, the
calls it must not make); the six texts with their follow-up or confirmation, provenance and
self-rating; and a checklist line per column for the author's review. The sheet is a reading
aid only: the JSON files stay the source of truth, and approval happens in the authoring tool
(a column flips to `provenance: "hand"` there).
"""

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

COLUMNS: Final = ("egy", "arabizi", "cs", "cs_latin", "en", "msa")
COLUMN_NAMES: Final = {
    "egy": "EGY",
    "arabizi": "Arabizi",
    "cs": "CS",
    "cs_latin": "CS-Latin",
    "en": "EN",
    "msa": "MSA",
}


def _args(args: dict[str, Any]) -> str:
    return ", ".join(
        f"{k}={'/'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in args.items()
    )


def _calls(calls: Sequence[dict[str, Any]] | None) -> str:
    return "; ".join(f"`{c['name']}({_args(c.get('args') or {})})`" for c in calls or []) or "—"


def _names(state: dict[str, Any]) -> dict[str, str]:
    """Record ids to display names, so expected calls read as people, not ids."""
    names: dict[str, str] = {}
    for collection in ("patients", "doctors"):
        for record in state.get(collection) or []:
            names[str(record["id"])] = str(record.get("name"))
    for record in state.get("beneficiaries") or []:
        names[str(record["account_id"])] = f"beneficiary {record.get('name')}"
    for record in state.get("accounts") or []:
        names.setdefault(str(record["id"]), f"{record.get('kind', 'account')} account")
    return names


def _what_happens(item: dict[str, Any]) -> list[str]:
    expected, behaviour = item["expected"], item["behaviour"]
    lines: list[str] = []
    if behaviour in ("act", "ask"):
        lines.append(f"- **Expected writes:** {_calls(expected.get('tool_calls'))}")
        if not expected.get("end_state_patch"):
            lines.append("- **The sandbox rejects that write** (state unchanged); reply says why")
    if behaviour == "ask":
        lines.append(
            f"- **Must ask about:** `{expected.get('expected_clarification')}` before any write"
        )
    if behaviour == "inform":
        lines.append(f"- **Reads:** {_calls(expected.get('read_calls'))}")
        for answer in expected.get("answer_must_contain") or []:
            forms = " · ".join(answer.get("forms") or [])
            lines.append(f"- **Answer must contain:** `{answer['value']}` (or: {forms})")
    if behaviour == "refuse":
        lines.append(f"- **Refuse** ({item.get('harm_type')}): no call that reveals or changes it")
    if behaviour == "none":
        lines.append("- **Do nothing** (the user aborts): no write, a short acknowledgement")
    if behaviour == "out_of_scope":
        lines.append("- **Out of scope**: say the tools cannot do this; no write")
    must_not = ", ".join(f"`{name}`" for name in expected.get("must_not_call") or [])
    lines.append(f"- **Must not call:** {must_not or '—'}")
    names = _names(item["initial_state"])
    ids = sorted(
        {
            str(v)
            for c in expected.get("tool_calls") or []
            for v in (c.get("args") or {}).values()
            if str(v) in names
        }
        | {str(v) for v in (item.get("slots") or {}).values() if str(v) in names}
    )
    if ids:
        lines.append("- **Who is who:** " + "; ".join(f"`{i}` = {names[i]}" for i in ids))
    return lines


def _column(name: str, block: dict[str, Any]) -> list[str]:
    extra = []
    if block.get("follow_up"):
        extra.append(f"follow-up: {block['follow_up']}")
    if block.get("confirm_yes"):
        extra.append(f"confirm: {block['confirm_yes']}")
    if block.get("insertions"):
        extra.append(
            "insertions: "
            + ", ".join(
                f"{i['text']}{' (tool cue)' if i.get('tool_cue') else ''}"
                for i in block["insertions"]
            )
        )
    lines = [f"- **{COLUMN_NAMES[name]}:** {block['text']}"]
    lines += [f"    - {e}" for e in extra]
    unrealised = [t for t, ok in (block.get("phenomenon_realised") or {}).items() if not ok]
    meta = f"natural {block.get('natural')}/5 · {block.get('provenance')}"
    if unrealised:
        meta += f" · not realised here: {', '.join(unrealised)}"
    lines.append(f"    - _{meta}_")
    return lines


def render_item(item: dict[str, Any]) -> list[str]:
    now = item["now"]
    when = dt.datetime.fromisoformat(now["local"])
    head = f"### {item['id']} · {item['behaviour']}"
    if item.get("harm_type"):
        head += f" ({item['harm_type'].replace('_', ' ')})"
    if item.get("control_of"):
        head += f" · control of {item['control_of']}"
    lines = [head, ""]
    lines.append(
        f"{now['weekday']} {when:%d/%m/%Y %H:%M} Cairo · speaker {item['gender']} · "
        f"{item['register']} · tags: {', '.join(item['phenomena'])}"
    )
    lines.append("")
    lines += _what_happens(item)
    lines.append("")
    for name in COLUMNS:
        lines += _column(name, item["texts"][name])
    lines.append("")
    boxes = " ".join(f"☐ {COLUMN_NAMES[c]}" for c in COLUMNS)
    lines += [f"Review: {boxes}", "", "Notes:", "", "---", ""]
    return lines


def render(items: Sequence[dict[str, Any]], *, title: str) -> str:
    behaviours = Counter(i["behaviour"] for i in items)
    drafts = sum(1 for i in items for c in COLUMNS if i["texts"][c].get("provenance") != "hand")
    lines = [
        f"# {title}",
        "",
        f"Generated {dt.date.today():%d %b %Y} from the scenario JSON in the repo "
        f"(`scripts/review_sheet.py`); regenerate after any change. {len(items)} scenarios; "
        + ", ".join(f"{b} {n}" for b, n in sorted(behaviours.items()))
        + f". Columns still marked `assistant_draft`: {drafts} of {len(items) * len(COLUMNS)}.",
        "",
        "How to review: read each column as a native speaker would type it. Approve or rewrite it "
        "in the authoring tool (open `tools/author/index.html`; see `docs/authoring.md`), "
        "which flips that column to `hand`; or write "
        "the change under Notes here and ask for it to be applied. Tick the boxes as you go.",
        "",
        "## Overview",
        "",
        "| Id | Behaviour | Tags | EGY |",
        "|---|---|---|---|",
    ]
    for item in items:
        kind = item["behaviour"] + (" (control)" if item.get("control_of") else "")
        egy = item["texts"]["egy"]["text"].replace("|", "/")
        lines.append(f"| {item['id']} | {kind} | {', '.join(item['phenomena'])} | {egy} |")
    lines.append("")
    domain = None
    for item in items:
        if item["domain"] != domain:
            domain = item["domain"]
            lines += [f"## {domain.capitalize()}", ""]
        lines += render_item(item)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("paths", type=Path, nargs="+", help="scenario files or directories")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", default="Scenario drafts for review")
    args = parser.parse_args(argv)
    files = sorted(
        f for p in args.paths for f in ([p] if p.is_file() else sorted(p.rglob("*.json")))
    )
    items = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    items = [i for i in items if isinstance(i, dict) and "texts" in i]
    items.sort(key=lambda i: (i["domain"] != "clinic", i["id"]))
    args.out.write_text(render(items, title=args.title) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} scenario(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
