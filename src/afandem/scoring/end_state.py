"""Expected end states: `expected.end_state_patch` applied to the initial state, and the diff.

Patch paths (docs/dataset-spec.md §1 example) are dot-separated segments; a segment is a field
name, optionally followed by `[key]` to select one record of a list:

- `collection[key]` with an object value: merge the fields into the record, or create the record
  when no record has that key (the key fields are filled in from the key, defaults from the
  domain model);
- `collection[key].field` (any depth): set one field of an existing record;
- `field` / `a.b`: set a top-level (or nested object) field;
- `{}`: the state is unchanged.

Record keys. A record is named by its `id` field; collections whose records have no `id` use a
comma-joined composite key (`COMPOSITE_KEYS`): clinic `slots[doctor_id,date,time]`
(`slots[d_2,2026-11-08,15:30]`); banking `cards[last4]` (`cards[4821]`) and
`beneficiaries[owner_id,account_id]` (`beneficiaries[c_1,acc_9]`). Everything else in the pilot
domains has an `id` (clinic `patients`, `doctors`, `appointments`; banking `accounts`,
`transactions`). Ids never contain `,`, `[` or `]` (the sandbox id pattern).

Generated records. The sandbox numbers new records from the state's `next_id` counter
(`appt_0001`, `txn_0001`, only once a call passes every check) and dates a transfer with the
state's `today`, so a created record has a predictable key and the patch names it:
`"transactions[txn_0001]": {"date": "2026-11-04", "from_account_id": "acc_1", ...}`.

Comparison rules (`state_diff`). Both sides are canonical states (`afandem.sandbox.canonical`)
compared field by field, records matched by key. Two things are ignored, and only these:
`next_id` (a counter fully determined by the records that exist) and, for banking transactions,
the free-text `note` when the expected record has none (the model may add any note to a
transfer; an expected note is compared exactly). The patched document is validated against the
domain state model, so a patch that breaks the state (an unknown field, an inconsistent booking)
is an error, not a silently impossible target.

Acceptable end states (`acceptable_states`, scorer v1). A field of `expected.tool_calls` that
holds a list admits several values, so an item can have several right end states. They are
enumerated τ-bench style: every combination of acceptable values (the cartesian product over the
listed fields of every expected call, at most `MAX_COMBINATIONS`) is replayed through the domain's
own tools on a fresh copy of the initial state, and each replay's canonical state is one
acceptable state. Replay was chosen over a field-wise comparison with the lists because one value
moves several records at once (another time frees and takes other slots, another doctor changes
the slot key, a created record gets the next counter id) and the sandbox already knows how; a
field-wise check would have to re-derive every such side effect. The replay is cross-checked:

- the first combination (every list's first value, the values the patch is authored with) must
  reach exactly the patched state (`expected_state`), so the patch and the expected calls can
  never disagree silently;
- every combination must be schema-valid and must end each call the way the first one does (a
  success where the gold call succeeds, the same error code where it is meant to fail, as in the
  banking over-limit items); an alternative the sandbox rejects is an authoring error, never a
  silent "state unchanged" that would let a do-nothing episode pass.

Either failure raises `AcceptableSetError` (a `PatchError`) before any provider call. The replay
acts as the scenario allows: on the clinic it marks every patient as located with name and phone
(the third-party rule is the model's job, not the gold's), so expected writes on a third party's
record replay without a lookup.
"""

import copy
import itertools
import json
import re
from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from afandem.sandbox import DOMAINS, canonical, new_state, registry_for
from afandem.sandbox.clinic import ClinicState
from afandem.scenarios import Scenario

type JSONDict = dict[str, Any]

COMPOSITE_KEYS: Final[Mapping[str, Mapping[str, tuple[str, ...]]]] = {
    "clinic": {"slots": ("doctor_id", "date", "time")},
    "banking": {"cards": ("last4",), "beneficiaries": ("owner_id", "account_id")},
}
IGNORED_TOP_LEVEL: Final = frozenset({"next_id"})
FREE_TEXT_FIELDS: Final[Mapping[str, Mapping[str, tuple[str, ...]]]] = {
    "banking": {"transactions": ("note",)},
}

_SEGMENT = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<key>[^\[\]]+)\])?")


MAX_COMBINATIONS: Final = 256


class PatchError(ValueError):
    """An `end_state_patch` that cannot be applied to the scenario's initial state."""


class AcceptableSetError(PatchError):
    """Expected calls whose replay disagrees with the patch or fails in the sandbox."""


def _record_model(domain: str, collection: str) -> type[BaseModel] | None:
    state_type, _ = DOMAINS[domain]
    info = state_type.model_fields.get(collection)
    if info is None:
        return None
    args: tuple[object, ...] = getattr(info.annotation, "__args__", ())
    if len(args) != 1:
        return None
    (item,) = args
    if isinstance(item, type) and issubclass(item, BaseModel):
        return item
    return None


def key_fields(domain: str, collection: str) -> tuple[str, ...]:
    """The fields that name one record of a top-level collection."""
    composite = COMPOSITE_KEYS.get(domain, {}).get(collection)
    if composite is not None:
        return composite
    model = _record_model(domain, collection)
    if model is not None and "id" in model.model_fields:
        return ("id",)
    raise PatchError(f"{domain}: {collection!r} is not a keyed collection")


def record_key(domain: str, collection: str, record: Mapping[str, Any]) -> str:
    return ",".join(str(record.get(name)) for name in key_fields(domain, collection))


def parse_path(path: str) -> list[tuple[str, str | None]]:
    """`a[k].b` -> `[("a", "k"), ("b", None)]`."""
    segments: list[tuple[str, str | None]] = []
    position = 0
    while True:
        match = _SEGMENT.match(path, position)
        if match is None:
            raise PatchError(f"bad patch path {path!r} at character {position}")
        segments.append((match["name"], match["key"]))
        position = match.end()
        if position == len(path):
            return segments
        if path[position] != ".":
            raise PatchError(f"bad patch path {path!r} at character {position}")
        position += 1


def _find(records: list[Any], domain: str, collection: str, key: str) -> JSONDict | None:
    fields = key_fields(domain, collection)
    if len(key.split(",")) != len(fields):
        raise PatchError(f"{collection}[{key}]: the key is {','.join(fields)}")
    for record in records:
        if isinstance(record, dict) and record_key(domain, collection, record) == key:
            return record
    return None


def _set_record(
    domain: str, records: list[Any], collection: str, key: str, value: JSONDict
) -> None:
    record = _find(records, domain, collection, key)
    if record is not None:
        record.update(copy.deepcopy(value))
        return
    created = dict(zip(key_fields(domain, collection), key.split(","), strict=True))
    created.update(copy.deepcopy(value))
    records.append(created)


def _apply_one(domain: str, doc: JSONDict, path: str, value: object) -> None:
    segments = parse_path(path)
    node: Any = doc
    for depth, (name, key) in enumerate(segments):
        last = depth == len(segments) - 1
        if not isinstance(node, dict):
            raise PatchError(f"{path}: {name!r} is not inside an object")
        if key is None:
            if last:
                node[name] = copy.deepcopy(value)
            elif name not in node:
                raise PatchError(f"{path}: no field {name!r}")
            else:
                node = node[name]
            continue
        records = node.get(name)
        if depth != 0 or not isinstance(records, list):
            raise PatchError(f"{path}: only top-level collections take a [key]")
        if last:
            if not isinstance(value, dict):
                raise PatchError(f"{path}: a record takes an object of fields")
            _set_record(domain, records, name, key, value)
            return
        node = _find(records, domain, name, key)
        if node is None:
            raise PatchError(f"{path}: no record {name}[{key}] to set a field on")


def apply_patch(domain: str, document: Mapping[str, Any], patch: Mapping[str, Any]) -> JSONDict:
    """Apply an `end_state_patch` to a canonical state document (a copy is returned)."""
    doc: JSONDict = copy.deepcopy(dict(document))
    for path, value in patch.items():
        _apply_one(domain, doc, path, value)
    return doc


def expected_state(scenario: Scenario) -> JSONDict:
    """The canonical state a successful episode ends in."""
    state = new_state(
        scenario.domain,
        scenario.initial_state,
        user_identity=scenario.user_identity,
        now=scenario.now.aware,
    )
    patched = apply_patch(scenario.domain, canonical(state), scenario.expected.end_state_patch)
    try:
        validated = type(state).model_validate(patched)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "<state>"
        message = f"{scenario.id}: the patched state is invalid: {where}: {first['msg']}"
        raise PatchError(message) from exc
    return canonical(validated)


def _free_text(domain: str, collection: str) -> tuple[str, ...]:
    return FREE_TEXT_FIELDS.get(domain, {}).get(collection, ())


def _keyed(domain: str, collection: str, records: list[Any]) -> dict[str, Any] | None:
    try:
        fields = key_fields(domain, collection)
    except PatchError:
        return None
    if not all(isinstance(r, dict) for r in records):
        return None
    keyed = {",".join(str(r.get(f)) for f in fields): r for r in records}
    return keyed if len(keyed) == len(records) else None


def _record_diff(
    domain: str, collection: str, path: str, actual: JSONDict, expected: JSONDict
) -> list[str]:
    differences: list[str] = []
    for name in sorted(set(actual) | set(expected)):
        if name in _free_text(domain, collection) and expected.get(name) is None:
            continue
        if actual.get(name) != expected.get(name) or (name in actual) != (name in expected):
            differences.append(f"{path}.{name}")
    return differences


def state_diff(domain: str, actual: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """Paths (in patch syntax) where two canonical states differ; [] means equal.

    A record only on one side is reported as `collection[key]` with ` (extra)` or
    ` (missing)`.
    """
    differences: list[str] = []
    for name in sorted(set(actual) | set(expected)):
        if name in IGNORED_TOP_LEVEL:
            continue
        mine, theirs = actual.get(name), expected.get(name)
        if isinstance(mine, list) and isinstance(theirs, list):
            keyed_mine, keyed_theirs = _keyed(domain, name, mine), _keyed(domain, name, theirs)
            if keyed_mine is not None and keyed_theirs is not None:
                for key in sorted(set(keyed_mine) | set(keyed_theirs)):
                    path = f"{name}[{key}]"
                    if key not in keyed_theirs:
                        differences.append(f"{path} (extra)")
                    elif key not in keyed_mine:
                        differences.append(f"{path} (missing)")
                    else:
                        differences += _record_diff(
                            domain, name, path, keyed_mine[key], keyed_theirs[key]
                        )
                continue
        if mine != theirs or (name in actual) != (name in expected):
            differences.append(name)
    return differences


type CallPlan = list[tuple[str, dict[str, Any]]]


def call_combinations(scenario: Scenario) -> list[CallPlan]:
    """Every combination of acceptable values of the expected calls, first values first."""
    slots: list[tuple[int, str, list[Any]]] = []
    for index, call in enumerate(scenario.expected.tool_calls):
        for field, value in call.args.items():
            if isinstance(value, list):
                if not value:
                    raise AcceptableSetError(
                        f"{scenario.id}: {call.name}.{field} lists no acceptable value"
                    )
                slots.append((index, field, list(value)))
    sizes = [len(options) for _, _, options in slots]
    total = 1
    for size in sizes:
        total *= size
    if total > MAX_COMBINATIONS:
        raise AcceptableSetError(
            f"{scenario.id}: {total} combinations of acceptable values (limit {MAX_COMBINATIONS})"
        )
    plans: list[CallPlan] = []
    for choice in itertools.product(*(options for _, _, options in slots)):
        chosen = {
            (index, field): value for (index, field, _), value in zip(slots, choice, strict=True)
        }
        plans.append(
            [
                (
                    call.name,
                    {
                        field: copy.deepcopy(chosen.get((index, field), value))
                        for field, value in call.args.items()
                    },
                )
                for index, call in enumerate(scenario.expected.tool_calls)
            ]
        )
    return plans


def _grant_replay(state: BaseModel) -> None:
    """Let the gold act on any record the scenario's calls name (clinic third parties)."""
    if isinstance(state, ClinicState):
        state.session.verified_patient_ids = [patient.id for patient in state.patients]


def _replay(scenario: Scenario, plan: CallPlan) -> tuple[JSONDict, list[str | None]]:
    state = new_state(
        scenario.domain,
        scenario.initial_state,
        user_identity=scenario.user_identity,
        now=scenario.now.aware,
    )
    _grant_replay(state)
    registry = registry_for(state)
    outcomes: list[str | None] = []
    for name, args in plan:
        record = registry.execute(state, name, json.dumps(args, ensure_ascii=False))
        if not record.call_valid:
            raise AcceptableSetError(
                f"{scenario.id}: expected call {name}({json.dumps(args, ensure_ascii=False)}) "
                f"is not valid: {record.result}"
            )
        error = record.result.get("error")
        outcomes.append(str(error) if error is not None else None)
    return canonical(state), outcomes


def acceptable_states(scenario: Scenario, *, expected: JSONDict | None = None) -> list[JSONDict]:
    """The canonical end states a successful episode may reach; the first is the patched one."""
    target = expected if expected is not None else expected_state(scenario)
    states: list[JSONDict] = []
    first: list[str | None] | None = None
    for number, plan in enumerate(call_combinations(scenario)):
        state, outcomes = _replay(scenario, plan)
        if first is None:
            first = outcomes
            differences = state_diff(scenario.domain, state, target)
            if differences:
                raise AcceptableSetError(
                    f"{scenario.id}: replaying expected.tool_calls (first values) does not reach "
                    f"end_state_patch: {', '.join(differences)}"
                )
            states.append(target)
            continue
        if outcomes != first:
            raise AcceptableSetError(
                f"{scenario.id}: acceptable-value combination {number + 1} ends {outcomes} in "
                f"the sandbox where the first values end {first}"
            )
        if all(state_diff(scenario.domain, state, known) for known in states):
            states.append(state)
    return states


def closest_diff(domain: str, actual: Mapping[str, Any], acceptable: list[JSONDict]) -> list[str]:
    """[] when `actual` is one of the acceptable states, else the shortest diff to one."""
    best: list[str] | None = None
    for state in acceptable:
        differences = state_diff(domain, actual, state)
        if not differences:
            return []
        if best is None or len(differences) < len(best):
            best = differences
    return best or []


__all__ = [
    "COMPOSITE_KEYS",
    "FREE_TEXT_FIELDS",
    "IGNORED_TOP_LEVEL",
    "MAX_COMBINATIONS",
    "AcceptableSetError",
    "PatchError",
    "acceptable_states",
    "apply_patch",
    "call_combinations",
    "closest_diff",
    "expected_state",
    "key_fields",
    "parse_path",
    "record_key",
    "state_diff",
]
