"""Command-line entry point.

    afandem run (--fake | --target NAME ...) [--scenarios PATH] [--columns c1,c2] [--run-id ID]
                [--runs-dir runs] [--resume] [--retry-errors] [--budget N] [--rpm R] [--no-cache]
                [--repeat K] [--concurrency N] [--overrides FILE] [--strict-drift] [--dry-run]
    afandem show RUN_DIR [--scenario ID] [--column C]
    afandem summary RUN_DIR
    afandem data lint PATH [--manual] [--canary-guid GUID] [--allow-drafts]

`afandem run` without `--fake` and without any provider key exits with code 2 before anything
else happens (no network). Real targets are resolved in one place, `_resolve_real_targets`.
Exit codes of `run`: 0 done, 2 usage or setup error, 3 budget stop, 4 quota stop, 5 drift stop
(`--strict-drift`). `data lint` exits 0 without errors, 1 with errors, 2 when PATH holds no
scenarios; `--allow-drafts` reports `assistant_draft` provenance as warnings (CI on pushes and
pull requests), never other provenance values, and the release workflow lints without it.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from afandem import __version__
from afandem.agent.prompts import PromptNotAuthoredError, PromptSet, PromptTemplateError
from afandem.canary import CANARY_GUID
from afandem.lints import lint_path
from afandem.providers.base import BudgetedProvider, CallBudget, Provider
from afandem.providers.cache import CacheLockedError, ResponseCache
from afandem.providers.fake import (
    FAKE_TARGET,
    OverrideNotApplicableError,
    fake_factory,
    load_overrides,
)
from afandem.providers.http import ProviderConfigError
from afandem.providers.routes import MissingKeyError, build_provider, route_names
from afandem.runner import (
    RunOptions,
    RunTarget,
    count_items,
    default_run_id,
    parameter_table,
    repeat_salt,
)
from afandem.runner import run as run_items
from afandem.scenarios import COLUMNS, LoadedScenario, ScenarioLoadError, load_scenarios
from afandem.scenarios.schema import Column
from afandem.scoring import PatchError
from afandem.trace import (
    INDEX_FILE,
    RunExistsError,
    TraceCorruptError,
    latest_records,
)

KEY_VARIABLES = (
    "GEMINI_FREE_API_KEY",
    "GROQ_API_KEY",
    "NVIDIA_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "FANAR_API_KEY",
    "OLLAMA_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_BILLED_API_KEY",
)
EXIT_USAGE = 2
DEFAULT_CACHE = Path("cache") / "responses.sqlite"


def _route_help() -> str:
    """`--target` help naming the configured routes; a wheel installed outside a checkout has
    no `config/routes.json`, and the CLI must still start (`--version`, `--help`, `data lint`)."""
    try:
        names = ", ".join(route_names())
    except (OSError, ValueError):
        return "a route from config/routes.json (repeatable; needs a repository checkout)"
    return f"a route from config/routes.json (repeatable): {names}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="afandem",
        description="Paired tool-use benchmark across English, MSA, Egyptian Arabic, "
        "Arabizi and code-switched Egyptian.",
    )
    parser.add_argument("--version", action="version", version=f"afandem {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run scenarios against models")
    who = run.add_mutually_exclusive_group()
    who.add_argument("--fake", action="store_true", help="offline fake model, no keys needed")
    who.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="NAME",
        help=_route_help(),
    )
    run.add_argument("--scenarios", type=Path, default=Path("data"), help="file or directory")
    run.add_argument("--columns", help="comma-separated columns (default: all six)")
    run.add_argument("--run-id", help="run directory name (required with --resume)")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.add_argument("--resume", action="store_true", help="skip items already done")
    run.add_argument(
        "--retry-errors", action="store_true", help="re-run provider_error items (implies --resume)"
    )
    run.add_argument("--budget", type=int, help="maximum number of uncached calls")
    run.add_argument("--rpm", type=float, help="requests per minute per route (real targets)")
    run.add_argument(
        "--no-cache",
        action="store_true",
        help="fresh calls: salt the cache with the run id (calls are still recorded)",
    )
    run.add_argument(
        "--cache", type=Path, default=DEFAULT_CACHE, help="response cache (real targets)"
    )
    run.add_argument("--repeat", type=int, default=1, metavar="K", help="repeats per item")
    run.add_argument("--concurrency", type=int, default=1, help="items in flight per target")
    run.add_argument("--overrides", type=Path, help="FakeModel overrides JSON (--fake only)")
    run.add_argument("--strict-drift", action="store_true", help="stop a target on model drift")
    run.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")

    show = sub.add_parser("show", help="print transcripts of a run for hand scoring")
    show.add_argument("run_dir", type=Path)
    show.add_argument("--scenario", help="only this scenario id")
    show.add_argument("--column", help="only this column")

    summary = sub.add_parser("summary", help="task-success counts per target and column")
    summary.add_argument("run_dir", type=Path)

    data = sub.add_parser("data", help="scenario data tools")
    data_sub = data.add_subparsers(dest="data_command")
    lint = data_sub.add_parser("lint", help="validate and lint scenario files")
    lint.add_argument("path", type=Path, help="a scenario file, data/<domain>/ or data/")
    lint.add_argument("--manual", action="store_true", help="also list the checks to do by hand")
    lint.add_argument(
        "--canary-guid", default=CANARY_GUID, help="project canary GUID (default: the project's)"
    )
    lint.add_argument(
        "--allow-drafts",
        action="store_true",
        help="report assistant_draft provenance as warnings, not errors (drafts still never "
        "enter the measured set; releases lint without this flag)",
    )
    return parser


def _error(message: str) -> int:
    print(f"afandem: {message}", file=sys.stderr)
    return EXIT_USAGE


def _resolve_real_targets(  # noqa: PLR0913
    names: Sequence[str],
    *,
    budget: CallBudget,
    cache: ResponseCache | None,
    no_cache: bool,
    rpm: float | None,
    run_id: str,
) -> list[RunTarget]:
    """The one place real targets are built.

    Each route gets `build_provider` (cache -> budget -> HTTP; cache hits never use budget).
    The base salt is None, or `nocache-<run_id>` with `--no-cache` (the cache still records the
    calls, so a shard can be exported); repeat k > 1 adds `repeat-<k>` (`repeat_salt`), built
    lazily, one provider per (route, repeat). Raises `MissingKeyError` before any network call.
    """
    base_salt = f"nocache-{run_id}" if no_cache else None
    targets: list[RunTarget] = []
    for name in names:
        target, first = build_provider(
            name, budget=budget, cache=cache, salt=base_salt, run_id=run_id, rpm=rpm
        )
        per_repeat: dict[int, Provider] = {1: first}

        def factory(
            scenario: object,
            column: object,
            repeat: int,
            *,
            name: str = name,
            per_repeat: dict[int, Provider] = per_repeat,
        ) -> Provider:
            del scenario, column  # one shared provider per repeat; the cache key holds the rest
            if repeat not in per_repeat:
                _, per_repeat[repeat] = build_provider(
                    name,
                    budget=budget,
                    cache=cache,
                    salt=repeat_salt(base_salt, repeat),
                    run_id=run_id,
                    rpm=rpm,
                )
            return per_repeat[repeat]

        targets.append(RunTarget(target, factory, salt=base_salt))
    return targets


def _parse_columns(raw: str | None) -> list[Column]:
    if raw is None:
        return list(COLUMNS)
    wanted = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in wanted if name not in COLUMNS]
    if unknown or not wanted:
        raise ValueError(f"unknown column(s) {unknown}; choose from {', '.join(COLUMNS)}")
    return [column for column in COLUMNS if column in wanted]


def _print_plan(
    scenarios: Sequence[LoadedScenario],
    columns: Sequence[Column],
    targets: Sequence[RunTarget],
    repeats: int,
    prompt: str,
) -> None:
    total = count_items(scenarios, columns, targets, repeats)
    print(
        f"dry run: {total} item(s) = {len(scenarios)} scenario(s) x {len(columns)} column(s) "
        f"x {len(targets)} target(s) x {repeats} repeat(s); columns: {', '.join(columns)}"
    )
    print(f"prompt: {prompt}")
    print("target | route | model | params_sent | provider_prefs")
    for row in parameter_table(targets):
        print(
            f"{row['name']} | {row['route']} | {row['model']} | "
            f"{_compact(row['params_sent'])} | {_compact(row['provider_prefs'])}"
        )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _run(args: argparse.Namespace) -> int:  # noqa: PLR0911
    if not args.fake:
        if not any(os.environ.get(name) for name in KEY_VARIABLES):
            print(
                "afandem run: no provider key found "
                f"({', '.join(KEY_VARIABLES)}); use --fake or load .env with "
                "`uv run --env-file .env afandem run`",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if not args.target:
            return _error("run: name at least one --target (or use --fake)")
        if args.overrides is not None:
            return _error("run: --overrides drives the fake model; it needs --fake")
    if args.retry_errors:
        args.resume = True
    if args.resume and not args.run_id:
        return _error("run: --resume needs --run-id")
    if args.repeat < 1 or args.concurrency < 1:
        return _error("run: --repeat and --concurrency must be >= 1")
    if args.budget is not None and args.budget < 0:
        return _error("run: --budget must be >= 0")
    try:
        columns = _parse_columns(args.columns)
        scenarios = load_scenarios(args.scenarios)
    except (ValueError, ScenarioLoadError) as exc:
        return _error(f"run: {exc}")
    if not scenarios:
        return _error(f"run: no scenarios under {args.scenarios}")
    run_id = args.run_id or default_run_id(fake=args.fake)
    budget = CallBudget(args.budget)
    cache_holder: list[ResponseCache | None] = [None]  # opened by _run_with, closed here
    try:
        return _run_with(
            args,
            scenarios=scenarios,
            columns=columns,
            run_id=run_id,
            budget=budget,
            cache_holder=cache_holder,
        )
    finally:
        if cache_holder[0] is not None:
            cache_holder[0].close()


def _run_with(  # noqa: PLR0911, PLR0913
    args: argparse.Namespace,
    *,
    scenarios: list[LoadedScenario],
    columns: list[Column],
    run_id: str,
    budget: CallBudget,
    cache_holder: list[ResponseCache | None],
) -> int:
    if args.fake:
        try:
            overrides = load_overrides(args.overrides)
        except (OSError, ValueError) as exc:
            return _error(f"run: --overrides: {exc}")

        def budgeted(provider: Provider) -> Provider:
            return BudgetedProvider(provider, budget)

        targets = [RunTarget(FAKE_TARGET, fake_factory(overrides, wrap=budgeted))]
    else:
        try:
            if not args.dry_run:
                args.cache.parent.mkdir(parents=True, exist_ok=True)
                cache_holder[0] = ResponseCache(args.cache)
            targets = _resolve_real_targets(
                args.target,
                budget=budget,
                cache=cache_holder[0],
                no_cache=args.no_cache,
                rpm=args.rpm,
                run_id=run_id,
            )
        except (MissingKeyError, CacheLockedError, ValueError) as exc:
            return _error(f"run: {exc}")
    try:
        prompts = PromptSet.load(allow_stub=args.fake)
    except PromptNotAuthoredError as exc:
        if args.dry_run:
            _print_plan(scenarios, columns, targets, args.repeat, f"NOT AUTHORED ({exc})")
            return 0
        return _error(f"run: {exc}")
    except PromptTemplateError as exc:
        return _error(f"run: {exc}")
    if args.dry_run:
        label = "offline-test stub" if prompts.is_stub else f"{prompts.source}"
        _print_plan(scenarios, columns, targets, args.repeat, f"{prompts.version} ({label})")
        return 0
    options = RunOptions(
        run_id=run_id,
        runs_dir=args.runs_dir,
        prompts=prompts,
        columns=columns,
        repeats=args.repeat,
        resume=args.resume,
        retry_errors=args.retry_errors,
        concurrency=args.concurrency,
        strict_drift=args.strict_drift,
        budget=budget,
    )
    try:
        result = asyncio.run(run_items(scenarios, targets, options))
    except (
        RunExistsError,
        PromptNotAuthoredError,
        PromptTemplateError,
        PatchError,
        OverrideNotApplicableError,
        TraceCorruptError,
        ProviderConfigError,
    ) as exc:
        return _error(f"run: {exc}")
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(result.outcomes.items())) or "none"
    print(
        f"run {run_id}: {result.written} item(s) written, {result.skipped} skipped; "
        f"outcomes: {outcomes}; stopped: {result.stopped or 'no'} -> {result.run_dir}"
    )
    return result.exit_code


# ---------------------------------------------------------------- show / summary


def _records(run_dir: Path) -> dict[str, dict[str, Any]]:
    if not (run_dir / INDEX_FILE).exists():
        raise FileNotFoundError(f"{run_dir} has no {INDEX_FILE}")
    return latest_records(run_dir)


def _call_line(call: dict[str, Any]) -> str:
    raw = call.get("arguments_raw")
    arguments = raw if isinstance(raw, str) else _compact(raw)
    levels = [
        name
        for name, on in (
            ("valid", call.get("call_valid")),
            ("write", call.get("attempted_write")),
            ("mutated", call.get("mutated")),
        )
        if on
    ]
    if not call.get("executed", True):
        levels.append("not executed")
    flags = call.get("validity_flags") or []
    detail = ", ".join(levels + flags) or "invalid"
    return f"  -> {call.get('name')}({arguments})  [{detail}]"


def _show_record(record: dict[str, Any]) -> None:
    scores = record.get("scores") or {}
    head = " | ".join(str(record.get(k)) for k in ("scenario_id", "column", "target", "repeat"))
    print(f"=== {head} ===")
    print(
        f"behaviour: {record.get('behaviour')}  outcome: {record.get('outcome')}"
        + (f" ({record.get('outcome_detail')})" if record.get("outcome_detail") else "")
        + f"  flags: {', '.join(record.get('flags') or []) or '-'}"
        + f"  follow-up: {'delivered' if record.get('follow_up_delivered') else 'no'}"
        + f" ({record.get('follow_up_rule')})"
    )
    print(
        f"score: task_success={scores.get('task_success')} "
        f"unsafe_read={scores.get('unsafe_read')} unsafe_write={scores.get('unsafe_write')}"
        + (f"  reasons: {'; '.join(scores.get('reasons') or [])}" if scores.get("reasons") else "")
    )
    calls = {c.get("call_id"): c for c in record.get("tool_calls", [])}
    for message in record.get("messages", []):
        role = message.get("role")
        if role == "system":
            print(
                f"[system] ({len(message.get('content') or '')} chars, "
                f"prompt {record.get('prompt_version')})"
            )
        elif role == "user":
            print(f"[user] {message.get('content')}")
        elif role == "assistant":
            content = message.get("content")
            print(f"[assistant] {content if content else '(no text)'}")
            for tool_call in message.get("tool_calls") or []:
                row = calls.get(tool_call.get("id"))
                if row is not None:
                    print(_call_line(row))
                else:
                    print(f"  -> {tool_call.get('name')}({tool_call.get('arguments')})")
        elif role == "tool":
            print(f"[tool {message.get('name')}] {message.get('content')}")
    print()


def _show(run_dir: Path, scenario: str | None, column: str | None) -> int:
    try:
        records = _records(run_dir)
    except (OSError, ValueError, TraceCorruptError) as exc:
        return _error(f"show: {exc}")
    shown = 0
    for key in sorted(records):
        record = records[key]
        if scenario is not None and record.get("scenario_id") != scenario:
            continue
        if column is not None and record.get("column") != column:
            continue
        _show_record(record)
        shown += 1
    if not shown:
        print("no matching items")
    return 0


def _summary(run_dir: Path) -> int:
    try:
        records = _records(run_dir)
    except (OSError, ValueError, TraceCorruptError) as exc:
        return _error(f"summary: {exc}")
    cells: dict[tuple[str, str], list[int]] = {}
    unscored: dict[str, int] = {}
    for record in records.values():
        target, column = str(record.get("target")), str(record.get("column"))
        success = (record.get("scores") or {}).get("task_success")
        if success is None:
            unscored[target] = unscored.get(target, 0) + 1
            continue
        cell = cells.setdefault((target, column), [0, 0])
        cell[0] += bool(success)
        cell[1] += 1
    targets = sorted({t for t, _ in cells} | set(unscored))
    columns = [c for c in COLUMNS if any(col == c for _, col in cells)]
    print(f"task success (successes/scored items), {run_dir.name}; descriptive only")
    width = max([len("target"), *(len(t) for t in targets)])
    print(" | ".join(["target".ljust(width), *(c.rjust(8) for c in columns), "unscored"]))
    for target in targets:
        row = []
        for column in columns:
            succeeded, scored = cells.get((target, column), [0, 0])
            row.append(f"{succeeded}/{scored}".rjust(8))
        print(" | ".join([target.ljust(width), *row, str(unscored.get(target, 0)).rjust(8)]))
    if not targets:
        print("(no items)")
    return 0


def _data_lint(path: Path, *, manual: bool, canary_guid: str | None, allow_drafts: bool) -> int:
    try:
        report = lint_path(path, canary_guid=canary_guid, allow_drafts=allow_drafts)
    except ScenarioLoadError as exc:
        print(f"afandem data lint: {exc}", file=sys.stderr)
        return 2
    for finding in report.findings:
        if manual or finding.severity != "manual":
            print(finding)
    drafts = sum(
        1
        for finding in report.findings
        if finding.rule == "provenance" and finding.severity == "warning"
    )
    print(
        f"{len(report.files)} file(s): {report.count('error')} error(s), "
        f"{report.count('warning')} warning(s), {report.count('manual')} manual check(s)"
        + ("" if manual or not report.count("manual") else " (--manual lists them)")
    )
    if drafts:
        print(
            f"{drafts} assistant_draft finding(s) reported as warnings (--allow-drafts): "
            "drafts stay out of the measured set until the author approves them"
        )
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "show":
        return _show(args.run_dir, args.scenario, args.column)
    if args.command == "summary":
        return _summary(args.run_dir)
    if args.command == "data" and args.data_command == "lint":
        return _data_lint(
            args.path,
            manual=args.manual,
            canary_guid=args.canary_guid,
            allow_drafts=args.allow_drafts,
        )
    _build_parser().print_help()
    return 0


__all__ = ["KEY_VARIABLES", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
