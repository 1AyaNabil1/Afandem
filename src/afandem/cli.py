"""Command-line entry point.

Phase 0 ships only the skeleton: `afandem --version` and `afandem run --fake`, which
exercises the CLI path in CI without keys or network. Phase 1 adds `afandem data lint`;
the other subcommands (run, score, report, aggregate, site, reproduce) follow.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from afandem import __version__
from afandem.canary import CANARY_GUID
from afandem.lints import lint_path
from afandem.scenarios import ScenarioLoadError

KEY_VARIABLES = (
    "GEMINI_FREE_API_KEY",
    "GROQ_API_KEY",
    "NVIDIA_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "FANAR_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_BILLED_API_KEY",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="afandem",
        description="Paired tool-use benchmark across English, MSA, Egyptian Arabic, "
        "Arabizi and code-switched Egyptian.",
    )
    parser.add_argument("--version", action="version", version=f"afandem {__version__}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run scenarios against models")
    run.add_argument("--fake", action="store_true", help="offline fake model, no keys needed")
    data = sub.add_parser("data", help="scenario data tools")
    data_sub = data.add_subparsers(dest="data_command")
    lint = data_sub.add_parser("lint", help="validate and lint scenario files")
    lint.add_argument("path", type=Path, help="a scenario file, data/<domain>/ or data/")
    lint.add_argument("--manual", action="store_true", help="also list the checks to do by hand")
    lint.add_argument(
        "--canary-guid", default=CANARY_GUID, help="project canary GUID (default: the project's)"
    )
    return parser


def _run(fake: bool) -> int:
    if fake:
        print("afandem run --fake: skeleton OK (scenarios and the fake model arrive in Phase 1)")
        return 0
    if not any(os.environ.get(name) for name in KEY_VARIABLES):
        print(
            "afandem run: no provider key found "
            f"({', '.join(KEY_VARIABLES)}); use --fake or load .env with "
            "`uv run --env-file .env afandem run`",
            file=sys.stderr,
        )
        return 2
    print("afandem run: real runs arrive in Phase 1", file=sys.stderr)
    return 2


def _data_lint(path: Path, *, manual: bool, canary_guid: str | None) -> int:
    try:
        report = lint_path(path, canary_guid=canary_guid)
    except ScenarioLoadError as exc:
        print(f"afandem data lint: {exc}", file=sys.stderr)
        return 2
    for finding in report.findings:
        if manual or finding.severity != "manual":
            print(finding)
    print(
        f"{len(report.files)} file(s): {report.count('error')} error(s), "
        f"{report.count('warning')} warning(s), {report.count('manual')} manual check(s)"
        + ("" if manual or not report.count("manual") else " (--manual lists them)")
    )
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run(fake=args.fake)
    if args.command == "data" and args.data_command == "lint":
        return _data_lint(args.path, manual=args.manual, canary_guid=args.canary_guid)
    _build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
