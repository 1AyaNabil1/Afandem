"""Command-line entry point.

Phase 0 ships only the skeleton: `afandem --version` and `afandem run --fake`, which
exercises the CLI path in CI without keys or network. The real subcommands (run, score,
report, aggregate, site, reproduce) arrive in Phase 1.
"""

import argparse
import os
import sys
from collections.abc import Sequence

from afandem import __version__

KEY_VARIABLES = ("OPENROUTER_API_KEY", "GEMINI_BILLED_API_KEY", "FANAR_API_KEY")


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


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run(fake=args.fake)
    _build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
