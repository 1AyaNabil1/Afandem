"""Loader: files and trees, errors that name the file, hashing, the committed JSON Schema."""

import json
from pathlib import Path
from typing import Any

import pytest

from afandem.scenarios import (
    ScenarioLoadError,
    canonical_json,
    load_scenario,
    load_scenarios,
    read_document,
    scenario_paths,
    scenario_sha256,
)
from afandem.scenarios.schema_export import (
    DEFAULT_SCHEMA_PATH,
    main,
    render_json_schema,
    scenario_json_schema,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
FIXTURE = FIXTURES / "clinic" / "clinic-0042.json"


def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def write(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def reversed_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: reversed_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reversed_keys(item) for item in value]
    return value


def test_load_one_file() -> None:
    loaded = load_scenario(FIXTURE)
    assert loaded.path == FIXTURE
    assert loaded.scenario.id == "clinic-0042"
    assert loaded.document == example()
    assert loaded.sha256 == scenario_sha256(example())
    assert len(loaded.sha256) == 64


def test_load_tree_and_domain_directory() -> None:
    assert [item.scenario.id for item in load_scenarios(FIXTURES)] == ["clinic-0042"]
    assert [item.scenario.id for item in load_scenarios(FIXTURES / "clinic")] == ["clinic-0042"]
    assert [item.scenario.id for item in load_scenarios(FIXTURE)] == ["clinic-0042"]


def test_tree_reads_only_domain_directories(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write(data / "clinic" / "clinic-0042.json", example())
    write(data / "schema" / "scenario.schema.json", {"title": "not a scenario"})
    write(data / "fixtures" / "doctors.json", [])
    (data / "banking").mkdir()
    assert scenario_paths(data) == [data / "clinic" / "clinic-0042.json"]
    assert scenario_paths(data / "banking") == []


def test_directory_without_domains_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ScenarioLoadError) as caught:
        scenario_paths(tmp_path)
    assert caught.value.path == tmp_path
    assert "no domain directories" in str(caught.value)


def test_missing_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ScenarioLoadError, match="no such file"):
        scenario_paths(tmp_path / "nope")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b'{"id": "clinic-0042",', "invalid JSON at line 1"),
        (b"\xff\xfe{}", "not valid UTF-8"),
        (b"[]", "one JSON object"),
        (b'{"id": "a", "id": "b"}', "duplicate key 'id'"),
        (b'{"revision": NaN}', "NaN is not valid JSON"),
        (b"\xef\xbb\xbf{}", "invalid JSON"),
    ],
)
def test_read_errors_name_the_file(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "clinic-0001.json"
    path.write_bytes(content)
    with pytest.raises(ScenarioLoadError) as caught:
        read_document(path)
    assert caught.value.path == path
    assert str(caught.value).startswith(f"{path}: ")
    assert message in caught.value.message


def test_schema_errors_name_the_file_and_location(tmp_path: Path) -> None:
    doc = example()
    doc["texts"]["egy"]["natural"] = 9
    path = write(tmp_path / "clinic" / "clinic-0042.json", doc)
    with pytest.raises(ScenarioLoadError) as caught:
        load_scenario(path)
    assert caught.value.path == path
    assert "texts.egy.natural" in caught.value.message


def test_tree_errors_name_the_bad_file(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "clinic-0042.json", example())
    bad = tmp_path / "clinic" / "clinic-0043.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ScenarioLoadError) as caught:
        load_scenarios(tmp_path)
    assert caught.value.path == bad


def test_duplicate_ids_are_an_error(tmp_path: Path) -> None:
    write(tmp_path / "clinic" / "a.json", example())
    second = write(tmp_path / "clinic" / "b.json", example())
    with pytest.raises(ScenarioLoadError, match="duplicate id 'clinic-0042'") as caught:
        load_scenarios(tmp_path)
    assert caught.value.path == second


def test_sha_is_stable_across_key_order_and_whitespace(tmp_path: Path) -> None:
    doc = example()
    reordered = reversed_keys(doc)
    assert list(reordered) != list(doc)
    assert scenario_sha256(reordered) == scenario_sha256(doc)
    compact = tmp_path / "clinic" / "clinic-0042.json"
    compact.parent.mkdir()
    compact.write_text(json.dumps(reordered, ensure_ascii=True), encoding="utf-8")
    assert load_scenario(compact).sha256 == load_scenario(FIXTURE).sha256


def test_sha_changes_with_any_value() -> None:
    doc = example()
    before = scenario_sha256(doc)
    doc["texts"]["en"]["natural"] = 4
    assert scenario_sha256(doc) != before


def test_canonical_json_keeps_arabic_and_sorts_keys() -> None:
    text = canonical_json(example())
    assert "\\u" not in text
    assert text.startswith('{"arabizi_variant":')
    assert text == canonical_json(reversed_keys(example()))
    assert "\n" not in text


def test_committed_json_schema_matches_the_model() -> None:
    committed = DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8")
    assert committed == render_json_schema(), (
        "data/schema/scenario.schema.json is stale: "
        "run `uv run python -m afandem.scenarios.schema_export`"
    )


def test_json_schema_shape() -> None:
    schema = scenario_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["x-schema-version"] == "1.0"
    assert schema["additionalProperties"] is False
    assert "register" in schema["properties"]
    assert "texts" in schema["required"]
    column = schema["$defs"]["ColumnText"]
    assert column["additionalProperties"] is False
    assert column["properties"]["provenance"]["enum"] == ["hand", "assistant_draft"]


def test_schema_export_check_and_write(tmp_path: Path) -> None:
    assert main(["--check"]) == 0
    output = tmp_path / "scenario.schema.json"
    assert main(["--check", "--output", str(output)]) == 1
    assert main(["--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == render_json_schema()
    assert main(["--check", "--output", str(output)]) == 0
