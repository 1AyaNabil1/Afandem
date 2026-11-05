"""The offline authoring tool (tools/author/) stays in step with the scenario schema.

The tool is plain browser JavaScript. These tests read its schema constants block and, when
Node.js is installed, run its model (tools/author/model.js) on the fixture scenario: the page
must write files the loader accepts, round-trip a valid file byte for byte, and reject what the
pydantic model rejects. They also guard the authoring rules: the tool ships no Arabic-script
text, no network reference, and never relabels provenance (an assistant draft stays one, through
edits and page reloads, until the author's explicit approve action for that column).
"""

import copy
import datetime as dt
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from afandem.canary import CANARY_STRING
from afandem.lints import lexicons
from afandem.lints.structure import _COLUMN_ONLY, CANARY_PREFIX, LENGTH_RATIO_MAX, LENGTH_RATIO_MIN
from afandem.lints.text import whitespace_tokens
from afandem.sandbox import BANKING_TOOLS, CLINIC_TOOLS
from afandem.scenarios.schema import (
    ARABIC_SCRIPT_COLUMNS,
    BEHAVIOURS,
    COLUMNS,
    CS_COLUMNS,
    CULTURAL_TAGS,
    DOMAIN_TOOLS,
    DOMAINS,
    ID_PATTERN,
    LATIN_ARABIZI_COLUMNS,
    LOCAL_DATETIME_PATTERN,
    NOISE_TAGS,
    ORTHOGRAPHIC_TAGS,
    SCHEMA_VERSION,
    WEEKDAYS,
    AnswerForm,
    ArabiziVariant,
    AuthoringBatch,
    ChangelogEntry,
    ColumnText,
    Expected,
    Gender,
    HarmType,
    Insertion,
    Now,
    Provenance,
    Register,
    Scenario,
    ToolCall,
    cairo_datetime,
)

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "author"
MODEL_JS = TOOL / "model.js"
FIXTURE = REPO / "tests" / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

ARABIC_SCRIPT = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufefc]")

DRIVER = r"""
const model = require(process.argv[2]);
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const jobs = JSON.parse(input);
  process.stdout.write(JSON.stringify(jobs.map(run)));
});
function run(job) {
  try {
    if (job.op === "load") {
      const loaded = model.fromDocument(job.doc, "2026-11-05");
      const report = model.validate(loaded.draft, job.options || {});
      return { ok: true, warnings: loaded.warnings, text: model.stringify(report.doc),
               errors: report.errors, hints: report.hints };
    }
    if (job.op === "empty") {
      const draft = model.emptyDraft("2026-11-05");
      const report = model.validate(draft);
      return { ok: true, draft: draft, doc: report.doc, errors: report.errors };
    }
    if (job.op === "measure") {
      return { ok: true, words: job.texts.map(model.countWords),
               chars: job.texts.map(model.countChars) };
    }
    if (job.op === "edit") {
      // Open a file, then replay what the page does: type, approve, undo, reload the page.
      let draft = model.fromDocument(job.doc, "2026-11-05").draft;
      const undone = [];
      for (const step of job.steps) {
        if (step.type) {
          const [target, field, value] = step.type;
          const block = target === "arabizi_variant" ? draft.arabiziVariant : draft.texts[target];
          block[field] = value;
        }
        if (step.approve) model.approve(draft, step.approve);
        if (step.undo) undone.push(model.undoApproval(draft, step.undo));
        if (step.reload) draft = model.reviveDraft(JSON.parse(JSON.stringify(draft)));
      }
      const report = model.validate(draft, {});
      return { ok: true, text: model.stringify(report.doc), drafts: model.assistantDrafts(draft),
               errors: report.errors, hints: report.hints, undone: undone,
               stored: JSON.parse(JSON.stringify(draft)) };
    }
    if (job.op === "revive") {
      const draft = model.reviveDraft(job.stored);
      return { ok: true, revived: draft !== null,
               text: draft === null ? null : model.stringify(model.toDocument(draft).doc) };
    }
    if (job.op === "now") return { ok: true, info: model.nowInfo(job.local, job.offset) };
    if (job.op === "json") return { ok: true, result: model.parseJsonText(job.text) };
    return { ok: false, error: "unknown op" };
  } catch (error) {
    return { ok: false, error: String(error && error.message) };
  }
}
"""


def run_model(jobs: list[dict[str, Any]], tmp_path: Path) -> list[dict[str, Any]]:
    """Run jobs through tools/author/model.js in Node and return one result per job."""
    assert NODE is not None
    driver = tmp_path / "driver.cjs"
    driver.write_text(DRIVER, encoding="utf-8")
    completed = subprocess.run(
        [NODE, str(driver), str(MODEL_JS)],
        input=json.dumps(jobs, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    results: list[dict[str, Any]] = json.loads(completed.stdout)
    return results


def schema_constants() -> dict[str, Any]:
    """The strict-JSON SCHEMA block of model.js."""
    source = MODEL_JS.read_text(encoding="utf-8")
    start = source.index("const SCHEMA = ") + len("const SCHEMA = ")
    end = source.index("// END SCHEMA CONSTANTS")
    data: dict[str, Any] = json.loads(source[start:end].strip().removesuffix(";"))
    return data


def field_keys(model: type[BaseModel]) -> list[str]:
    """JSON keys of a model in declaration order (aliases applied)."""
    return [info.alias or name for name, info in model.model_fields.items()]


def fixture_document() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def dumps(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ constants


def test_enums_match_the_schema() -> None:
    c = schema_constants()
    assert c["schema_version"] == SCHEMA_VERSION
    assert c["id_pattern"] == ID_PATTERN
    assert c["local_datetime_pattern"] == LOCAL_DATETIME_PATTERN
    assert c["tz"] == "Africa/Cairo"
    assert c["domains"] == list(DOMAINS)
    assert set(c["pilot_domains"]) == {"clinic", "banking"}
    assert c["behaviours"] == list(BEHAVIOURS)
    assert c["columns"] == list(COLUMNS)
    assert c["weekdays"] == list(WEEKDAYS)
    assert c["harm_types"] == list(get_args(HarmType))
    assert c["genders"] == list(get_args(Gender))
    assert c["registers"] == list(get_args(Register))
    assert c["authoring_batches"] == list(get_args(AuthoringBatch))
    assert c["cultural_tags"] == list(CULTURAL_TAGS)
    assert c["orthographic_tags"] == list(ORTHOGRAPHIC_TAGS)
    assert set(c["noise_tags"]) == set(NOISE_TAGS)
    assert c["arabic_script_columns"] == list(ARABIC_SCRIPT_COLUMNS)
    assert c["latin_arabizi_columns"] == list(LATIN_ARABIZI_COLUMNS)
    assert c["cs_columns"] == list(CS_COLUMNS)
    assert c["reply_language"] == "user"
    assert c["provenances"] == list(get_args(Provenance))
    assert c["provenance"] == "hand"  # what every column of a new scenario carries


def test_domain_tools_match_the_schema_and_the_sandboxes() -> None:
    tools = schema_constants()["domain_tools"]
    assert tools == {domain: dict(table) for domain, table in DOMAIN_TOOLS.items()}
    for domain in DOMAINS:
        assert list(tools[domain]) == list(DOMAIN_TOOLS[domain])
    for registry in (CLINIC_TOOLS, BANKING_TOOLS):
        table = tools[registry.domain]
        assert list(table) == registry.names()
        assert {name for name, writes in table.items() if writes} == registry.mutating()


def test_key_orders_match_the_models() -> None:
    order = schema_constants()["key_order"]
    assert order["scenario"] == field_keys(Scenario)
    assert order["changelog_entry"] == field_keys(ChangelogEntry)
    assert order["now"] == field_keys(Now)
    assert order["expected"] == field_keys(Expected)
    assert order["tool_call"] == field_keys(ToolCall)
    assert order["answer_form"] == field_keys(AnswerForm)
    assert order["column_text"] == field_keys(ColumnText)
    assert order["insertion"] == field_keys(Insertion)
    assert order["arabizi_variant"] == field_keys(ArabiziVariant)


def test_lint_constants_match_the_lints() -> None:
    c = schema_constants()
    assert c["length_ratio"] == [LENGTH_RATIO_MIN, LENGTH_RATIO_MAX]
    assert c["canary_prefix"] == CANARY_PREFIX
    lex = lexicons.code_switch()
    assert c["insertions"] == [lex.min_insertions, lex.max_insertions]
    assert c["column_only_tags"] == {tag: list(cols) for tag, cols in _COLUMN_ONLY.items()}


def test_canary_txt_is_the_project_canary() -> None:
    path = TOOL / "canary.txt"
    if not path.exists():
        pytest.skip("tools/author/canary.txt is optional")
    assert path.read_text(encoding="utf-8").strip() == CANARY_STRING


# ------------------------------------------------------------------ authoring rules


def tool_files() -> list[Path]:
    return sorted(p for p in TOOL.iterdir() if p.suffix in {".html", ".js", ".css", ".txt"})


def test_the_tool_ships_no_arabic_script_text() -> None:
    """Every scenario text is typed by the author; the tool carries none, in any column."""
    files = tool_files()
    assert {p.name for p in files} >= {"index.html", "app.js", "model.js", "style.css"}
    for path in files:
        found = ARABIC_SCRIPT.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} contains Arabic-script characters {found[:5]}"


def test_the_tool_is_offline() -> None:
    """No server, network, CDN, web font or module script: it runs from file://."""
    network = re.compile(r"https?://|//cdn|@import|\burl\(|type=\"module\"|\bimport\s*\(")
    for path in tool_files():
        text = path.read_text(encoding="utf-8")
        assert not network.findall(text), f"{path.name} references the network"
    html = (TOOL / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert (TOOL / ref).is_file(), f"index.html references a missing file {ref}"


def test_placeholders_are_neutral() -> None:
    """Placeholders describe the field ("type the ... text"); none is a sample sentence."""
    source = (TOOL / "app.js").read_text(encoding="utf-8")
    placeholders = re.findall(r'placeholder:\s*"([^"]*)"', source)
    assert placeholders
    for text in placeholders:
        assert len(text.split()) <= 8, text


# ------------------------------------------------------------------ the model, through Node


@needs_node
def test_the_fixture_round_trips_byte_for_byte(tmp_path: Path) -> None:
    doc = fixture_document()
    options = {"projectCanary": CANARY_STRING}
    [result] = run_model([{"op": "load", "doc": doc, "options": options}], tmp_path)
    assert result["ok"], result
    assert result["warnings"] == []
    assert result["errors"] == []
    assert result["hints"] == []
    assert result["text"] == FIXTURE.read_text(encoding="utf-8")
    Scenario.model_validate(json.loads(result["text"]))


@needs_node
def test_a_new_scenario_starts_with_no_text(tmp_path: Path) -> None:
    [result] = run_model([{"op": "empty"}], tmp_path)
    assert result["ok"], result
    draft, doc = result["draft"], result["doc"]
    for column in COLUMNS:
        block = draft["texts"][column]
        assert block["text"] == block["follow_up"] == block["confirm_yes"] == ""
        assert block.get("insertions", []) == []
        assert block["natural"] is None
        assert block["provenance"] == doc["texts"][column]["provenance"] == "hand"
    assert draft["arabiziVariant"] == {
        "enabled": False,
        "text": "",
        "provenance": "hand",
        "openedAs": None,
    }
    assert [entry["note"] for entry in draft["meta"]["changelog"]] == [""]
    assert [row["value"] for row in draft["slots"]] == [""]
    assert draft["canary"] == ""
    assert result["errors"], "an empty scenario must not look valid"


def _mutate(doc: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    change(out)
    return out


def _set(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        target: Any = doc
        for key in parents:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

    return change


def _all(*changes: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        for step in changes:
            step(doc)

    return change


def _drop_slot(doc: dict[str, Any]) -> None:
    del doc["slots"]["intent"]


def _confirms_to_follow_ups(doc: dict[str, Any]) -> None:
    """Turn the act item into an ask item using its own (author-written) texts."""
    for block in doc["texts"].values():
        block["follow_up"], block["confirm_yes"] = block["confirm_yes"], None


def _no_confirms(doc: dict[str, Any]) -> None:
    for block in doc["texts"].values():
        block["confirm_yes"] = None


INVALID: dict[str, Callable[[dict[str, Any]], None]] = {
    "inform_with_a_write": _set("behaviour", "inform"),
    "act_without_confirm": _set("texts.en.confirm_yes", None),
    "read_tool_as_write": _set("expected.tool_calls.0.name", "find_patient"),
    "dst_gap": _all(_set("now.local", "2026-04-24T00:30:00"), _set("now.weekday", "Friday")),
    "dst_repeated_hour": _all(
        _set("now.local", "2026-10-29T23:30:00"), _set("now.weekday", "Thursday")
    ),
    "wrong_offset": _all(
        _set("now.local", "2026-11-04T10:00:00+03:00"), _set("now.weekday", "Wednesday")
    ),
    "must_not_call_clash": _set("expected.must_not_call", ["reschedule_appointment"]),
    "no_intent": _drop_slot,
    "changelog_gap": _set("revision", 3),
    "fixed_after_post_pilot": _set("authoring_batch", "post_pilot"),
    "own_control_twin": _set("control_of", "clinic-0042"),
    "foreign_tool": _set("tools", [*DOMAIN_TOOLS["clinic"], "transfer"]),
    "empty_identity": _set("user_identity", {}),
    "natural_out_of_range": _set("texts.egy.natural", 6),
    "blank_text": _set("texts.msa.text", "   "),
    "float_slot": _set("slots.days_ahead", 4.5),
    "float_answer_value": _set("expected.answer_must_contain", [{"value": 1.5, "forms": ["1.5"]}]),
    "ask_without_clarification": _all(_set("behaviour", "ask"), _confirms_to_follow_ups),
    "ask_clarifies_unknown_slot": _all(
        _set("behaviour", "ask"),
        _confirms_to_follow_ups,
        _set("expected.expected_clarification", "not_a_slot"),
    ),
    "refuse_without_harm_type": _all(
        _set("behaviour", "refuse"),
        _no_confirms,
        _set("expected.tool_calls", []),
        _set("expected.end_state_patch", {}),
    ),
}

VALID: dict[str, Callable[[dict[str, Any]], None]] = {
    "explicit_offset_in_repeated_hour": _all(
        _set("now.local", "2026-10-29T23:30:00+02:00"), _set("now.weekday", "Thursday")
    ),
    "none_item": _all(
        _set("behaviour", "none"),
        _no_confirms,
        _set("expected.tool_calls", []),
        _set("expected.end_state_patch", {}),
    ),
    "inform_item": _all(
        _set("behaviour", "inform"),
        _no_confirms,
        _set("expected.tool_calls", []),
        _set("expected.end_state_patch", {}),
        _set(
            "expected.read_calls",
            [{"name": "get_appointments", "args": {"patient_id": "p_17"}}],
        ),
        _set("expected.answer_must_contain", [{"value": "2026-11-05", "forms": ["2026-11-05"]}]),
    ),
    "refuse_item": _all(
        _set("behaviour", "refuse"),
        _no_confirms,
        _set("expected.tool_calls", []),
        _set("expected.end_state_patch", {}),
        _set("harm_type", "inferable_mismatch"),
    ),
    "ask_item": _all(
        _set("behaviour", "ask"),
        _confirms_to_follow_ups,
        _set("expected.expected_clarification", "new_time"),
    ),
}


@needs_node
def test_the_page_rejects_what_the_schema_rejects(tmp_path: Path) -> None:
    base = fixture_document()
    docs = {name: _mutate(base, change) for name, change in INVALID.items()}
    results = run_model([{"op": "load", "doc": doc} for doc in docs.values()], tmp_path)
    for (name, doc), result in zip(docs.items(), results, strict=True):
        with pytest.raises(ValidationError):
            Scenario.model_validate(doc)
        assert result["ok"], (name, result)
        assert result["errors"], f"{name}: the page found no problem"


@needs_node
def test_the_page_accepts_what_the_schema_accepts(tmp_path: Path) -> None:
    base = fixture_document()
    docs = {name: _mutate(base, change) for name, change in VALID.items()}
    results = run_model([{"op": "load", "doc": doc} for doc in docs.values()], tmp_path)
    for (name, doc), result in zip(docs.items(), results, strict=True):
        Scenario.model_validate(doc)
        assert result["ok"], (name, result)
        assert result["errors"] == [], (name, result["errors"])
        assert result["text"] == dumps(doc), f"{name}: the page changed a valid file"
        Scenario.model_validate(json.loads(result["text"]))


# ------------------------------------------------------------------ provenance

DRAFT = "assistant_draft"
VARIANT = "arabizi_variant"
TARGETS = [*COLUMNS, VARIANT]


def provenance_block(doc: dict[str, Any], target: str) -> dict[str, Any]:
    block: dict[str, Any] = doc[VARIANT] if target == VARIANT else doc["texts"][target]
    return block


def drafted(*targets: str) -> dict[str, Any]:
    """The fixture with these columns (or the variant) marked as drafted by the assistant."""
    doc = fixture_document()
    for target in targets:
        provenance_block(doc, target)["provenance"] = DRAFT
    return doc


def provenances(doc: dict[str, Any]) -> dict[str, str]:
    return {target: provenance_block(doc, target)["provenance"] for target in TARGETS}


@needs_node
@pytest.mark.parametrize(
    "targets", [TARGETS, ["egy", "en", VARIANT], ["msa"]], ids=["all", "mixed", "one"]
)
def test_a_draft_file_round_trips_byte_for_byte(tmp_path: Path, targets: list[str]) -> None:
    doc = drafted(*targets)
    Scenario.model_validate(doc)
    loaded, reloaded = run_model(
        [{"op": "load", "doc": doc}, {"op": "edit", "doc": doc, "steps": [{"reload": True}]}],
        tmp_path,
    )
    assert loaded["ok"], loaded
    assert loaded["warnings"] == []
    assert loaded["errors"] == [], "an assistant draft passes the schema"
    assert loaded["text"] == dumps(doc)
    assert reloaded["text"] == dumps(doc), "a page reload must keep the drafts"
    assert sorted(reloaded["drafts"]) == sorted(targets)
    flagged = [hint for hint in loaded["hints"] if hint["kind"] == "provenance"]
    assert len(flagged) == len(targets), "each draft is flagged, as the lint does"
    assert [hint for hint in loaded["hints"] if hint["kind"] != "provenance"] == []


@needs_node
def test_editing_a_draft_column_keeps_it_a_draft(tmp_path: Path) -> None:
    doc = drafted("egy", "en", VARIANT)
    texts = doc["texts"]
    # The edits rearrange the fixture's own (author-written) texts.
    egy = texts["egy"]["confirm_yes"]
    en = texts["en"]["text"] + " " + texts["en"]["confirm_yes"]
    variant = doc[VARIANT]["text"] + " " + texts["arabizi"]["confirm_yes"]
    steps = [
        {"type": ["egy", "text", ""]},
        {"type": ["egy", "text", egy]},
        {"type": ["en", "text", en]},
        {"reload": True},
        {"type": [VARIANT, "text", variant]},
    ]
    [result] = run_model([{"op": "edit", "doc": doc, "steps": steps}], tmp_path)
    assert result["ok"], result
    expected = copy.deepcopy(doc)
    expected["texts"]["egy"]["text"] = egy
    expected["texts"]["en"]["text"] = en
    expected[VARIANT]["text"] = variant
    assert result["text"] == dumps(expected)
    saved = json.loads(result["text"])
    assert provenances(saved) == {
        t: DRAFT if t in ("egy", "en", VARIANT) else "hand" for t in TARGETS
    }
    Scenario.model_validate(saved)


@needs_node
def test_approving_flips_only_that_column(tmp_path: Path) -> None:
    doc = drafted(*TARGETS)
    jobs = [{"op": "edit", "doc": doc, "steps": [{"approve": target}]} for target in TARGETS]
    for target, result in zip(TARGETS, run_model(jobs, tmp_path), strict=True):
        assert result["ok"], result
        expected = copy.deepcopy(doc)
        provenance_block(expected, target)["provenance"] = "hand"
        assert result["text"] == dumps(expected), target
        assert sorted(result["drafts"]) == sorted(t for t in TARGETS if t != target)


@needs_node
def test_an_approval_can_be_undone_only_for_a_drafted_column(tmp_path: Path) -> None:
    doc = drafted("cs")
    steps = [{"approve": "cs"}, {"reload": True}, {"undo": "cs"}, {"undo": "egy"}]
    hand = fixture_document()
    undone, untouched = run_model(
        [
            {"op": "edit", "doc": doc, "steps": steps},
            {"op": "edit", "doc": hand, "steps": [{"undo": "cs"}]},
        ],
        tmp_path,
    )
    assert undone["undone"] == [True, False]
    assert undone["text"] == dumps(doc)
    assert untouched["undone"] == [False]
    assert untouched["text"] == dumps(hand)


def _drop(path: str) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        target: Any = doc
        for key in parents:
            target = target[key]
        del target[last]

    return change


UNKNOWN_PROVENANCE: list[Any] = ["llm", None, "Hand", "", "assistant-draft", "hand "]


@needs_node
def test_provenance_is_never_relabelled(tmp_path: Path) -> None:
    """Unknown provenance values are refused, never rewritten as hand or assistant_draft."""
    base = fixture_document()
    docs = [
        _mutate(base, _set(f"{where}.provenance", value))
        for value in UNKNOWN_PROVENANCE
        for where in ("texts.en", VARIANT)
    ]
    docs.append(_mutate(base, _drop("texts.cs.provenance")))
    docs.append(
        _mutate(
            base,
            _all(
                _set("texts.cs.text", ""),
                _set("texts.cs.confirm_yes", ""),
                _set("texts.cs.provenance", "llm"),
            ),
        )
    )
    results = run_model([{"op": "load", "doc": doc} for doc in docs], tmp_path)
    for doc, result in zip(docs, results, strict=True):
        with pytest.raises(ValidationError):
            Scenario.model_validate(doc)
        assert not result["ok"], result
        assert "hand-written" in result["error"]


@needs_node
def test_a_stored_draft_never_relabels(tmp_path: Path) -> None:
    """The page keeps its draft in localStorage; reviving it must not change provenance."""
    doc = drafted("egy", VARIANT)
    hand = fixture_document()
    drafted_store, hand_store = (
        result["stored"]
        for result in run_model(
            [{"op": "edit", "doc": d, "steps": []} for d in (doc, hand)], tmp_path
        )
    )
    unreadable = copy.deepcopy(drafted_store)
    unreadable["texts"]["egy"]["provenance"] = "llm"
    # A draft stored before provenance was kept per column could only hold hand-written text.
    legacy = copy.deepcopy(hand_store)
    for block in [*legacy["texts"].values(), legacy["arabiziVariant"]]:
        del block["provenance"], block["openedAs"]
    kept, refused, old = run_model(
        [{"op": "revive", "stored": s} for s in (drafted_store, unreadable, legacy)], tmp_path
    )
    assert kept["text"] == dumps(doc)
    assert refused["revived"] is False
    assert old["text"] == dumps(hand)


@needs_node
def test_json_areas_reject_duplicate_keys(tmp_path: Path) -> None:
    texts = ['{"a": 1, "a": 2}', '[{"name": "x", "args": {}, "args": {}}]', '{"a": {"b": 1}}']
    results = run_model([{"op": "json", "text": t} for t in texts], tmp_path)
    assert [r["result"]["ok"] for r in results] == [False, False, True]
    assert "duplicate key" in results[0]["result"]["error"]


@needs_node
def test_word_and_character_counts_match_the_lint(tmp_path: Path) -> None:
    texts = [
        "",
        "a b",
        "  a\tb\nc  ",
        "a\u00a0b",
        "a\u2009b\u3000c",
        "a\x1cb\x85c",
        "a\ufeffb",
        "a\u200bb",
        "x\u2028y\u2029z",
    ]
    [result] = run_model([{"op": "measure", "texts": texts}], tmp_path)
    assert result["words"] == [whitespace_tokens(t) for t in texts]
    assert result["chars"] == [sum(1 for ch in t if not ch.isspace()) for t in texts]


@needs_node
def test_the_clock_matches_the_schema(tmp_path: Path) -> None:
    moments = [
        ("2026-11-04T10:00:00", ""),
        ("2026-04-23T23:59:59", ""),
        ("2026-04-24T00:30:00", ""),
        ("2026-04-24T01:00:00", ""),
        ("2026-10-29T22:59:59", ""),
        ("2026-10-29T23:30:00", ""),
        ("2026-10-29T23:30:00", "+03:00"),
        ("2026-10-30T00:00:00", ""),
        ("2027-02-08T21:30:00", ""),
        ("2027-02-08T21:30:00", "+03:00"),
    ]
    jobs = [{"op": "now", "local": local, "offset": offset} for local, offset in moments]
    results = run_model(jobs, tmp_path)
    for (local, offset), result in zip(moments, results, strict=True):
        info = result["info"]
        moment = dt.datetime.fromisoformat(local + offset)
        assert info["weekday"] == WEEKDAYS[moment.weekday()]
        try:
            cairo_datetime(moment)
        except ValueError:
            assert info["error"], (local, offset)
        else:
            assert info["error"] is None, (local, offset, info["error"])
