"""Export the scenario JSON Schema to `data/schema/scenario.schema.json`.

Run `uv run python -m afandem.scenarios.schema_export` after changing the models, or
`--check` to fail when the committed file is stale (a test does the same).
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from afandem.scenarios.schema import SCHEMA_VERSION, Scenario

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA_PATH = REPO_ROOT / "data" / "schema" / "scenario.schema.json"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def scenario_json_schema() -> dict[str, Any]:
    """The JSON Schema generated from `Scenario` (validation mode)."""
    schema = Scenario.model_json_schema(mode="validation")
    return {"$schema": JSON_SCHEMA_DIALECT, "x-schema-version": SCHEMA_VERSION, **schema}


def render_json_schema() -> str:
    """The exact text written to the schema file."""
    return json.dumps(scenario_json_schema(), indent=2, ensure_ascii=False) + "\n"


def write_json_schema(path: Path = DEFAULT_SCHEMA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json_schema(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args(argv)
    output: Path = args.output
    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else ""
        if current != render_json_schema():
            print(
                f"{output} is stale; run python -m afandem.scenarios.schema_export", file=sys.stderr
            )
            return 1
        return 0
    write_json_schema(output)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
