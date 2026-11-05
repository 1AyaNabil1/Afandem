"""Export one run's cached responses as immutable shards, or import a shard (harness spec §6).

    uv run python scripts/export_cache.py export RUN_ID                  # every target of the run
    uv run python scripts/export_cache.py export RUN_ID --target qwen3.8-27b@groq
    uv run python scripts/export_cache.py import cache/shards/<target>-<run_id>.jsonl.gz

Shards are written to cache/shards/<target>-<run_id>.jsonl.gz (deterministic gzip, sorted
keys) and never overwritten: exporting the same content again is a no-op, different content
is refused. Export reads the database without taking the writer lock; import takes it.
"""

import argparse
import sys
from pathlib import Path

from afandem.providers.cache import (
    ResponseCache,
    ShardExistsError,
    export_shard,
    import_shard,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "cache" / "responses.sqlite"
DEFAULT_OUT = ROOT / "cache" / "shards"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite cache path")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="write one shard per target of a run")
    export.add_argument("run_id")
    export.add_argument("--target", action="append", help="target label (repeatable)")
    export.add_argument("--out", type=Path, default=DEFAULT_OUT, help="shard directory")
    imp = sub.add_parser("import", help="load shards into the cache")
    imp.add_argument("shards", nargs="+", type=Path)
    return parser


def _export(db: Path, run_id: str, targets: list[str] | None, out: Path) -> int:
    with ResponseCache(db, readonly=True) as cache:
        chosen = targets or cache.run_targets(run_id)
        if not chosen:
            print(f"no calls recorded for run {run_id!r} in {db}", file=sys.stderr)
            return 1
        status = 0
        for target in chosen:
            try:
                path = export_shard(cache, run_id, target, out)
            except (ShardExistsError, ValueError) as exc:
                print(f"{target}: {exc}", file=sys.stderr)
                status = 1
                continue
            print(f"{target}: {path}")
        return status


def _import(db: Path, shards: list[Path]) -> int:
    with ResponseCache(db) as cache:
        for shard in shards:
            added = import_shard(cache, shard)
            print(f"{shard}: {added} new response(s)")
    return 0


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    if args.command == "export":
        return _export(args.db, args.run_id, args.target, args.out)
    return _import(args.db, args.shards)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
