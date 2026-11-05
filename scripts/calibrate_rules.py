"""Check the Phase 1 rule classifier and the claims-done lexicon against blind labels (κ gate).

    uv run python scripts/calibrate_rules.py sample RUN_DIR --scenarios data --out DIR
    uv run python scripts/calibrate_rules.py kappa DIR --scenarios data

`sample` draws turn-1 replies from a run, stratified by column (and spread across targets
inside each column), and writes a blind labelling packet: `packet.jsonl` and `packet.md` show
the user's turn-1 text, the turn-1 tool calls with their results and the turn-1 reply, with
the model, the scenario id and every rule output hidden. `key.json` maps each sample id back to
its trace and is not for the labeller. The labeller writes `labels.jsonl`, one line per sample:

    {"sample_id": "s07", "label": "ask", "about": "patient_phone", "claims_done": false}

`label` is one of ask, confirm, answer, acknowledge, claims_done, other (harness spec §8, the
judge's turn-1 set); `about` is the scenario's expected clarification slot, "other", or null
(only for `ask`); `claims_done` says whether the reply states that the requested action was
done, whatever else it does.

`kappa` recomputes the rule outputs from the traces (`classify_turn1`, `claims_done`) and
writes `kappa.json` and `kappa.md`: Cohen's κ with a bootstrap 95% interval for the turn-1
label and for claims-done, per-column κ, `about` agreement, the confusion matrix and every
disagreement. The plan's gate is κ ≥ 0.6 on 60 pilot replies against the author's labels.
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from afandem.scenarios import Scenario, load_scenarios
from afandem.scoring.behaviour import claims_done, classify_turn1
from afandem.trace import latest_records

LABELS: Final = ("ask", "confirm", "answer", "acknowledge", "claims_done", "other")
COLUMNS: Final = ("en", "msa", "egy", "arabizi", "cs", "cs_latin")
DEFAULT_SEED: Final = 20261105
BOOTSTRAP: Final = 2000
GATE: Final = 0.6


# ---------------------------------------------------------------- reading a trace


def user_text(record: Mapping[str, Any]) -> str:
    """The user's turn-1 message."""
    for message in record.get("messages") or []:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def reply_text(record: Mapping[str, Any]) -> str:
    """The assistant's turn-1 reply text ("" when turn 1 ended without one)."""
    for turn in record.get("turns") or []:
        if turn.get("turn") == 1:
            return str(turn.get("text") or "")
    return ""


def turn1_calls(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": call.get("name"),
            "arguments": call.get("arguments_parsed", call.get("arguments_raw")),
            "result": call.get("result"),
        }
        for call in record.get("tool_calls") or []
        if call.get("turn") == 1
    ]


# ---------------------------------------------------------------- sample


def draw(
    records: Mapping[str, Mapping[str, Any]],
    per_column: int,
    seed: int,
    exclude: frozenset[str] = frozenset(),
) -> list[tuple[str, Mapping[str, Any]]]:
    """`per_column` ok items per column, round-robin over targets, in a seeded order. Keys in
    `exclude` (scenario|column|target|repeat) are skipped: a cached call returns the same reply,
    so an item labelled in an earlier sample is not fresh in a later run."""
    rng = random.Random(seed)
    chosen: list[tuple[str, Mapping[str, Any]]] = []
    for column in COLUMNS:
        by_target: dict[str, list[str]] = defaultdict(list)
        for key in sorted(records):
            record = records[key]
            if key in exclude:
                continue
            if record.get("column") == column and record.get("outcome") == "ok":
                by_target[str(record.get("target"))].append(key)
        for keys in by_target.values():
            rng.shuffle(keys)
        targets = sorted(by_target)
        rng.shuffle(targets)
        picked: list[str] = []
        while len(picked) < per_column and any(by_target[t] for t in targets):
            for target in targets:
                if by_target[target] and len(picked) < per_column:
                    picked.append(by_target[target].pop())
        chosen += [(key, records[key]) for key in picked]
    rng.shuffle(chosen)
    return chosen


def _packet_md(rows: Sequence[Mapping[str, Any]]) -> str:
    out = [
        "# Blind labelling packet",
        "",
        "One block per reply. Model, scenario id and rule outputs are hidden. Label the turn-1",
        "reply only (the last line of each block); the tool calls show what happened before it.",
        "",
    ]
    for row in rows:
        out += [f"## {row['sample_id']} · column `{row['column']}`", ""]
        out += [f"**User:** {row['user_text']}", ""]
        if row["tool_calls"]:
            out.append("**Tool calls in turn 1:**")
            out.append("")
            for call in row["tool_calls"]:
                arguments = json.dumps(call["arguments"], ensure_ascii=False)
                result = json.dumps(call["result"], ensure_ascii=False)
                out.append(f"- `{call['name']}` {arguments} → {result}")
            out.append("")
        else:
            out += ["**Tool calls in turn 1:** none", ""]
        slot = row["expected_clarification"]
        out += [f"**Expected clarification slot (for `about`):** {slot or '—'}", ""]
        out += [f"**Reply:** {row['reply'] or '(empty)'}", ""]
    return "\n".join(out)


def sample(
    run_dir: Path,
    scenarios: Mapping[str, Scenario],
    out: Path,
    n: int,
    seed: int,
    *,
    exclude: Sequence[Path] = (),
) -> int:
    records = latest_records(run_dir)
    skip = frozenset(
        str(entry["trace_key"])
        for path in exclude
        for entry in json.loads(path.read_text(encoding="utf-8")).values()
    )
    chosen = draw(records, n, seed, skip)
    out.mkdir(parents=True, exist_ok=True)
    rows, key = [], {}
    for index, (trace_key, record) in enumerate(chosen, start=1):
        sample_id = f"s{index:02d}"
        scenario = scenarios.get(str(record.get("scenario_id")))
        slot = scenario.expected.expected_clarification if scenario else None
        rows.append(
            {
                "sample_id": sample_id,
                "column": record.get("column"),
                "user_text": user_text(record),
                "tool_calls": turn1_calls(record),
                "reply": reply_text(record),
                "expected_clarification": slot,
            }
        )
        key[sample_id] = {
            "trace_key": trace_key,
            "run_dir": str(run_dir),
            "scenario_id": record.get("scenario_id"),
            "target": record.get("target"),
            "behaviour": record.get("behaviour"),
        }
    with (out / "packet.jsonl").open("w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    (out / "packet.md").write_text(_packet_md(rows) + "\n", encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n")
    by_column = Counter(str(row["column"]) for row in rows)
    spread = ", ".join(f"{column}={by_column[column]}" for column in COLUMNS)
    print(f"wrote {len(rows)} sample(s) to {out} ({spread})")
    return 0


# ---------------------------------------------------------------- kappa


def cohen_kappa(left: Sequence[str], right: Sequence[str]) -> float | None:
    """Unweighted Cohen's κ; None when undefined (no items, or chance agreement is 1)."""
    total = len(left)
    if total == 0:
        return None
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / total
    first, second = Counter(left), Counter(right)
    expected = sum(first[c] * second[c] for c in set(first) | set(second)) / total**2
    if expected >= 1:
        return None
    return (observed - expected) / (1 - expected)


def bootstrap(
    left: Sequence[str], right: Sequence[str], seed: int = DEFAULT_SEED
) -> tuple[float, float] | None:
    """Percentile 95% interval of κ over item resamples (undefined resamples skipped)."""
    if not left:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    indices = range(len(left))
    for _ in range(BOOTSTRAP):
        picks = [rng.choice(indices) for _ in indices]
        value = cohen_kappa([left[i] for i in picks], [right[i] for i in picks])
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _interval(pair: tuple[float, float] | None) -> str:
    return "—" if pair is None else f"[{pair[0]:.2f}, {pair[1]:.2f}]"


def _matrix(human: Sequence[str], rule: Sequence[str]) -> list[str]:
    counts = Counter(zip(human, rule, strict=True))
    header = "| labeller ↓ / rule → | " + " | ".join(LABELS) + " |"
    lines = [header, "|---" * (len(LABELS) + 1) + "|"]
    for row in LABELS:
        cells = " | ".join(str(counts[(row, col)] or "") for col in LABELS)
        lines.append(f"| **{row}** | {cells} |")
    return lines


def kappa(directory: Path, scenarios: Mapping[str, Scenario], labels_file: Path) -> int:
    key = json.loads((directory / "key.json").read_text(encoding="utf-8"))
    packet = {row["sample_id"]: row for row in _read_jsonl(directory / "packet.jsonl")}
    labels = {row["sample_id"]: row for row in _read_jsonl(labels_file)}
    missing = sorted(set(packet) - set(labels))
    unknown = sorted({row["label"] for row in labels.values()} - set(LABELS))
    if missing or unknown:
        print(f"labels missing for {missing}; unknown labels {unknown}", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    for sample_id in sorted(packet):
        item, mine = packet[sample_id], labels[sample_id]
        slot = item["expected_clarification"]
        verdict = classify_turn1(item["reply"], slot)
        rows.append(
            {
                "sample_id": sample_id,
                "column": item["column"],
                "target": key[sample_id]["target"],
                "scenario_id": key[sample_id]["scenario_id"],
                "human": mine["label"],
                "rule": verdict.label,
                "human_about": mine.get("about"),
                "rule_about": verdict.about,
                "human_claims": bool(mine["claims_done"]),
                "rule_claims": claims_done(item["reply"]),
                "note": mine.get("note", ""),
                "reply": item["reply"],
            }
        )
    human = [r["human"] for r in rows]
    rule = [r["rule"] for r in rows]
    human_claims = [str(r["human_claims"]) for r in rows]
    rule_claims = [str(r["rule_claims"]) for r in rows]
    both_ask = [r for r in rows if r["human"] == r["rule"] == "ask"]
    per_column = {
        column: cohen_kappa(
            [r["human"] for r in rows if r["column"] == column],
            [r["rule"] for r in rows if r["column"] == column],
        )
        for column in COLUMNS
    }
    result: dict[str, Any] = {
        "n": len(rows),
        "turn1": {
            "kappa": cohen_kappa(human, rule),
            "ci95": bootstrap(human, rule),
            "agreement": sum(a == b for a, b in zip(human, rule, strict=True)) / len(rows),
        },
        "claims_done": {
            "kappa": cohen_kappa(human_claims, rule_claims),
            "ci95": bootstrap(human_claims, rule_claims),
            "agreement": sum(a == b for a, b in zip(human_claims, rule_claims, strict=True))
            / len(rows),
        },
        "about": {
            "both_ask": len(both_ask),
            "agree": sum(r["human_about"] == r["rule_about"] for r in both_ask),
        },
        "per_column_kappa": per_column,
        "gate": GATE,
        "rows": rows,
    }
    (directory / "kappa.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (directory / "kappa.md").write_text(_kappa_md(result) + "\n", encoding="utf-8")
    turn1 = result["turn1"]
    print(
        f"turn-1 κ = {_fmt(turn1['kappa'])} {_interval(turn1['ci95'])}; claims-done κ = "
        f"{_fmt(result['claims_done']['kappa'])} {_interval(result['claims_done']['ci95'])}; "
        f"n = {len(rows)} -> {directory / 'kappa.md'}"
    )
    return 0


def _kappa_md(result: Mapping[str, Any]) -> str:
    turn1, claims = result["turn1"], result["claims_done"]
    passed = turn1["kappa"] is not None and turn1["kappa"] >= GATE
    lines = [
        "# Rule classifier vs blind labels",
        "",
        f"n = {result['n']} turn-1 replies. Gate: κ ≥ {GATE} (plan §7, Phase 1 decision rules).",
        "",
        "| Check | κ | 95% bootstrap interval | Raw agreement |",
        "|---|---|---|---|",
        f"| Turn-1 label (6 classes) | {_fmt(turn1['kappa'])} | {_interval(turn1['ci95'])} "
        f"| {turn1['agreement']:.0%} |",
        f"| Claims-done (yes/no) | {_fmt(claims['kappa'])} | {_interval(claims['ci95'])} "
        f"| {claims['agreement']:.0%} |",
        "",
        f"Turn-1 gate: **{'met' if passed else 'not met'}** on this sample. `about` agrees on "
        f"{result['about']['agree']} of {result['about']['both_ask']} replies both label `ask`.",
        "",
        "Per-column turn-1 κ (about 10 replies each, so wide): "
        + ", ".join(f"{c} {_fmt(v)}" for c, v in result["per_column_kappa"].items()),
        "",
        "## Confusion matrix (turn-1 label)",
        "",
        *_matrix([r["human"] for r in result["rows"]], [r["rule"] for r in result["rows"]]),
        "",
        "## Disagreements",
        "",
        "| Sample | Column | Labeller | Rule | Claims (labeller / rule) | Reply | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        if r["human"] != r["rule"] or r["human_claims"] != r["rule_claims"]:
            reply = " ".join(str(r["reply"]).split())
            reply = (reply[:160] + "…") if len(reply) > 160 else reply
            reply = reply.replace("|", "\\|")
            lines.append(
                f"| {r['sample_id']} | {r['column']} | {r['human']} | {r['rule']} | "
                f"{r['human_claims']} / {r['rule_claims']} | {reply or '(empty)'} | "
                f"{str(r['note']).replace('|', '/')} |"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI


def _scenarios(paths: Iterable[Path]) -> dict[str, Scenario]:
    return {item.scenario.id: item.scenario for path in paths for item in load_scenarios(path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="draw a blind labelling packet from a run")
    s.add_argument("run_dir", type=Path)
    s.add_argument("--scenarios", type=Path, action="append", required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--per-column", type=int, default=10)
    s.add_argument("--seed", type=int, default=DEFAULT_SEED)
    s.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        help="key.json of an earlier sample whose items are not fresh (repeatable)",
    )
    k = sub.add_parser("kappa", help="compare labels.jsonl with the rule outputs")
    k.add_argument("directory", type=Path)
    k.add_argument("--scenarios", type=Path, action="append", required=True)
    k.add_argument("--labels", type=Path, help="default: DIRECTORY/labels.jsonl")
    args = parser.parse_args(argv)
    scenarios = _scenarios(args.scenarios)
    if args.command == "sample":
        return sample(
            args.run_dir, scenarios, args.out, args.per_column, args.seed, exclude=args.exclude
        )
    return kappa(args.directory, scenarios, args.labels or args.directory / "labels.jsonl")


if __name__ == "__main__":
    sys.exit(main())
