"""Typed tool registry, canonical schemas, and `execute` with the three call levels.

A tool is a plain function `fn(state, args) -> dict` registered with `@registry.tool(mutates=…)`.
Its `Args` model (a pydantic model with `extra="forbid"`) is the single source of truth: it
generates the JSON schema sent to models and validates incoming calls. Schemas are canonicalised
before sending and hashing: no `title`, `$ref`/`$defs` inlined, optional fields flattened to
their non-null type, `additionalProperties: false` on objects, keys and `required` sorted.

`execute` records, for every call:

- `call_valid`: the arguments parsed as a JSON object and validated against the `Args` model.
- `attempted_write`: a valid call to a mutating tool, executed whatever it returned.
- `mutated`: the canonical state differs before and after the call.

Validity flags are computed on the parsed arguments before validation (pydantic would accept
`int("٣")`-style input in lax mode): `invented_tool`, `malformed`, `schema_invalid`,
`arabic_keys`, `non_ascii_digits`. Results carry error codes, never prose.
"""

import copy
import inspect
import json
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError

from afandem.sandbox.names import has_arabic

type JSONDict = dict[str, Any]
type ToolFn[S, A] = Callable[[S, A], JSONDict]

FLAG_ORDER: tuple[str, ...] = (
    "invented_tool",
    "malformed",
    "schema_invalid",
    "arabic_keys",
    "non_ascii_digits",
)
NON_CANONICAL_FIELDS: frozenset[str] = frozenset({"session"})


def dumps(value: object) -> str:
    """Serialise a tool result as sent to the model: Arabic stays Arabic."""
    return json.dumps(value, ensure_ascii=False)


def _sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canonical_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted((_canonical_value(item) for item in value), key=_sort_key)
    return value


def canonical(state: BaseModel) -> JSONDict:
    """Order-insensitive JSON form of a state for end-state comparison.

    Keys are sorted, every list is sorted by its items' canonical JSON, and episode bookkeeping
    (the `session` field) is left out.
    """
    dumped = state.model_dump(mode="json", exclude=set(NON_CANONICAL_FIELDS))
    result = _canonical_value(dumped)
    assert isinstance(result, dict)
    return result


def canonical_json(state: BaseModel) -> str:
    return _sort_key(canonical(state))


def _canonical_schema(node: Mapping[str, Any], defs: Mapping[str, Any]) -> JSONDict:
    work = dict(node)
    ref = work.pop("$ref", None)
    if isinstance(ref, str):
        work = {**defs[ref.removeprefix("#/$defs/")], **work}
    work.pop("$defs", None)
    work.pop("title", None)
    any_of = work.get("anyOf")
    if isinstance(any_of, list):
        non_null = [s for s in any_of if s != {"type": "null"}]
        if len(non_null) == 1 and len(non_null) < len(any_of):
            del work["anyOf"]
            work = {**_canonical_schema(non_null[0], defs), **work}
            if "default" in work and work["default"] is None:
                del work["default"]
    out: JSONDict = {}
    for key, value in work.items():
        if key == "properties":
            out[key] = {name: _canonical_schema(value[name], defs) for name in sorted(value)}
        elif key in ("items", "not") or (key == "additionalProperties" and isinstance(value, dict)):
            out[key] = _canonical_schema(value, defs)
        elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            out[key] = [_canonical_schema(item, defs) for item in value]
        elif key == "required":
            out[key] = sorted(value)
        else:
            out[key] = value
    if out.get("type") == "object" and not isinstance(out.get("additionalProperties"), dict):
        out["additionalProperties"] = False
    return {key: out[key] for key in sorted(out)}


def canonical_schema(schema: Mapping[str, Any]) -> JSONDict:
    """Flat, title-free, key-sorted JSON schema with `additionalProperties: false`."""
    return _canonical_schema(schema, schema.get("$defs", {}))


@dataclass(frozen=True)
class ToolSpec[S: BaseModel]:
    name: str
    description: str
    parameters: JSONDict
    args_model: type[BaseModel]
    fn: Callable[[S, Any], JSONDict]
    mutates: bool

    def as_json(self) -> JSONDict:
        """`{name, description, parameters}`; providers wrap it in their own envelope."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class CallRecord(BaseModel):
    """What one tool call did, as recorded in the trace."""

    model_config = ConfigDict(frozen=True)

    name: str
    arguments_raw: str | dict[str, Any]
    arguments_parsed: dict[str, Any] | None
    call_valid: bool
    attempted_write: bool
    mutated: bool
    validity_flags: list[str]
    result: dict[str, Any]

    @property
    def content(self) -> str:
        """The tool message content sent back to the model."""
        return dumps(self.result)


def _has_non_ascii_digit(text: str) -> bool:
    return any(unicodedata.category(c) == "Nd" and not "0" <= c <= "9" for c in text)


def argument_flags(arguments: object) -> list[str]:
    """`arabic_keys` / `non_ascii_digits` found anywhere in parsed arguments (keys and values)."""
    found: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    if has_arabic(key):
                        found.add("arabic_keys")
                    if _has_non_ascii_digit(key):
                        found.add("non_ascii_digits")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and _has_non_ascii_digit(value):
            found.add("non_ascii_digits")

    walk(arguments)
    return [flag for flag in FLAG_ORDER if flag in found]


def _ordered(flags: set[str]) -> list[str]:
    return [flag for flag in FLAG_ORDER if flag in flags]


def _parse(raw: str | Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, str):
        return copy.deepcopy(dict(raw)), None
    if not raw.strip():
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "malformed_json"
    if not isinstance(parsed, dict):
        return None, "not_an_object"
    return parsed, None


def _invalid_detail(exc: ValidationError, spec: ToolSpec[Any]) -> list[JSONDict]:
    properties: Mapping[str, Any] = spec.parameters.get("properties", {})
    detail: list[JSONDict] = []
    for error in exc.errors(include_url=False):
        item: JSONDict = {"code": error["type"]}
        field = ".".join(str(part) for part in error["loc"])
        if field:
            item["field"] = field
        allowed = properties.get(field, {}).get("enum")
        if error["type"] == "literal_error" and allowed:
            item["allowed"] = list(allowed)
        detail.append(item)
    return detail


def invalid_arguments(detail: list[JSONDict]) -> JSONDict:
    return {"error": "invalid_arguments", "detail": detail}


class ToolRegistry[S: BaseModel]:
    """The tools of one domain, bound to its state model."""

    def __init__(self, domain: str, state_type: type[S]) -> None:
        if state_type in _REGISTRIES:
            raise ValueError(f"{state_type.__name__} already has a tool registry")
        self.domain = domain
        self.state_type = state_type
        self._tools: dict[str, ToolSpec[S]] = {}
        _REGISTRIES[state_type] = self

    def tool[A: BaseModel](self, *, mutates: bool) -> Callable[[ToolFn[S, A]], ToolFn[S, A]]:
        """Register `fn(state, args) -> dict`; its docstring becomes the tool description."""

        def register(fn: ToolFn[S, A]) -> ToolFn[S, A]:
            name = getattr(fn, "__name__", "")
            if list(inspect.signature(fn).parameters) != ["state", "args"]:
                raise TypeError(f"tool {name} must take exactly (state, args)")
            hints = get_type_hints(fn)
            if hints.get("state") is not self.state_type:
                raise TypeError(f"tool {name}: state must be {self.state_type.__name__}")
            args_model = hints.get("args")
            if not (isinstance(args_model, type) and issubclass(args_model, BaseModel)):
                raise TypeError(f"tool {name}: args must be a pydantic model")
            if args_model.model_config.get("extra") != "forbid":
                raise TypeError(f"tool {name}: {args_model.__name__} must set extra='forbid'")
            description = inspect.getdoc(fn)
            if not description:
                raise TypeError(f"tool {name} needs a docstring (its description)")
            if name in self._tools:
                raise ValueError(f"tool {name} registered twice in {self.domain}")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                parameters=canonical_schema(args_model.model_json_schema()),
                args_model=args_model,
                fn=fn,
                mutates=mutates,
            )
            return fn

        return register

    def __getitem__(self, name: str) -> ToolSpec[S]:
        return self._tools[name]

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[ToolSpec[S]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)

    def mutating(self) -> frozenset[str]:
        return frozenset(name for name, spec in self._tools.items() if spec.mutates)

    def tools_json(self) -> list[JSONDict]:
        """Every tool's canonical `{name, description, parameters}`, in registration order."""
        return [spec.as_json() for spec in self._tools.values()]

    def tools_canonical_json(self) -> str:
        """The canonical JSON snapshotted into `runs/<id>/tools.json` and hashed."""
        return _sort_key(self.tools_json())

    def execute(self, state: S, name: str, raw_arguments: str | Mapping[str, Any]) -> CallRecord:
        """Run one model tool call against `state` (mutated in place) and record it."""
        raw: str | dict[str, Any] = (
            raw_arguments if isinstance(raw_arguments, str) else copy.deepcopy(dict(raw_arguments))
        )
        parsed, problem = _parse(raw_arguments)
        flags = set(argument_flags(parsed)) if parsed is not None else set()
        spec = self._tools.get(name)

        def record(result: JSONDict, *, valid: bool = False, mutated: bool = False) -> CallRecord:
            return CallRecord(
                name=name,
                arguments_raw=raw,
                arguments_parsed=copy.deepcopy(parsed),
                call_valid=valid,
                attempted_write=valid and spec is not None and spec.mutates,
                mutated=mutated,
                validity_flags=_ordered(flags),
                result=result,
            )

        if spec is None:
            flags.add("invented_tool")
            if parsed is None:
                flags.add("malformed")
            return record({"error": "unknown_tool"})
        if parsed is None:
            flags.add("malformed")
            return record(invalid_arguments([{"code": problem}]))
        try:
            args = spec.args_model.model_validate(parsed)
        except ValidationError as exc:
            flags.add("schema_invalid")
            return record(invalid_arguments(_invalid_detail(exc, spec)))
        before = canonical(state)
        result = spec.fn(state, args)
        return record(result, valid=True, mutated=canonical(state) != before)


_REGISTRIES: dict[type[BaseModel], ToolRegistry[Any]] = {}


def registry_for(state: BaseModel | type[BaseModel]) -> ToolRegistry[Any]:
    state_type = state if isinstance(state, type) else type(state)
    try:
        return _REGISTRIES[state_type]
    except KeyError:
        raise KeyError(f"no tool registry for {state_type.__name__}") from None


def execute(state: BaseModel, name: str, raw_arguments: str | Mapping[str, Any]) -> CallRecord:
    """Execute a tool call against a domain state, dispatching on the state's type."""
    return registry_for(state).execute(state, name, raw_arguments)
