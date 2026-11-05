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

Acceptable-value lists with more than one value describe several acceptable end states; v0
compares against the single patched state (the patch is authored with the first value), and the
acceptable-set comparison arrives with the normalisers in sub-budget (c).
"""

import copy
import re
from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from afandem.sandbox import DOMAINS, canonical, new_state
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


class PatchError(ValueError):
    """An `end_state_patch` that cannot be applied to the scenario's initial state."""


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


__all__ = [
    "COMPOSITE_KEYS",
    "FREE_TEXT_FIELDS",
    "IGNORED_TOP_LEVEL",
    "PatchError",
    "apply_patch",
    "expected_state",
    "key_fields",
    "parse_path",
    "record_key",
    "state_diff",
]
