"""Helpers that read a scenario's state: records, names and aliases."""

from collections.abc import Iterator, Mapping
from typing import Any

from afandem.lints.text import fold, is_arabic, tokens


def iter_dicts(value: Any) -> Iterator[Mapping[str, Any]]:
    """Every JSON object nested anywhere in `value` (depth first)."""
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_dicts(item)


def records_with_id(state: Mapping[str, Any], record_id: str) -> list[Mapping[str, Any]]:
    return [record for record in iter_dicts(state) if record.get("id") == record_id]


def record_names(record: Mapping[str, Any]) -> list[str]:
    """The record's `name` and `aliases` strings."""
    names: list[str] = []
    name = record.get("name")
    if isinstance(name, str):
        names.append(name)
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        names.extend(alias for alias in aliases if isinstance(alias, str))
    return names


def latin_name_tokens(state: Mapping[str, Any]) -> frozenset[str]:
    """Casefolded Latin tokens of every name and alias in the state (spelling-lint exempt)."""
    found: set[str] = set()
    for record in iter_dicts(state):
        for name in record_names(record):
            found.update(token for token in tokens(fold(name)) if not is_arabic(token))
    return frozenset(found)
