"""Call-level metrics: validity counts, tool selection and argument accuracy (harness-spec §8).

- **Validity** counts the flags of every call attempt (`invented_tool`, `malformed`,
  `schema_invalid`, `arabic_keys`, `non_ascii_digits`, `truncated_tool_call`) plus
  `empty_reply` (a turn that ended in a reply with no content and no call); an item is `valid`
  when every count is zero.
- **Tool selection** = the multiset of validated writes (`attempted_write`, whatever the sandbox
  returned), each distinct (tool, normalised arguments) counted once, equals the multiset of
  `expected.tool_calls` names; reads are ignored, and any extra write fails it (so does a write
  retried with other arguments after an error: two distinct writes against one expected).
  Computed for every behaviour: an item that expects no write passes when it made none.
- **Argument accuracy** = the share of expected argument fields that match, after
  normalisation, on the *last* schema-valid call of each expected tool (the last k calls when k
  calls of one tool are expected, paired in order); a missing call scores every field of it 0.
  Fields are listed as `tool.field` (`tool[i].field` for repeated tools). None for items with no
  expected write.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict

from afandem.agent.loop import CallRow, TurnRecord
from afandem.providers.base import canonical_json
from afandem.scenarios import Scenario
from afandem.scoring.normalise import arg_matches, normalised_args

VALIDITY_FLAGS: Final = (
    "invented_tool",
    "malformed",
    "schema_invalid",
    "arabic_keys",
    "non_ascii_digits",
    "truncated_tool_call",
    "empty_reply",
)


class Validity(BaseModel):
    """Validity flag counts of one item (`calls` = call attempts, executed or not)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invented_tool: int = 0
    malformed: int = 0
    schema_invalid: int = 0
    arabic_keys: int = 0
    non_ascii_digits: int = 0
    truncated_tool_call: int = 0
    empty_reply: int = 0
    calls: int = 0
    invalid_calls: int = 0

    @property
    def valid(self) -> bool:
        return not any(getattr(self, flag) for flag in VALIDITY_FLAGS)

    def flags(self) -> dict[str, int]:
        return {flag: getattr(self, flag) for flag in VALIDITY_FLAGS}


def validity(calls: Sequence[CallRow], turns: Sequence[TurnRecord]) -> Validity:
    counts: Counter[str] = Counter()
    for call in calls:
        counts.update(flag for flag in call.validity_flags if flag in VALIDITY_FLAGS)
    counts["empty_reply"] = sum(
        1 for t in turns if t.end == "reply" and not (t.reply or "").strip()
    )
    return Validity(
        **{flag: counts[flag] for flag in VALIDITY_FLAGS},
        calls=len(calls),
        invalid_calls=sum(1 for call in calls if not call.call_valid),
    )


def write_signature(call: CallRow) -> tuple[str, str]:
    """(tool, canonical normalised arguments): one validated write, for de-duplication."""
    return call.name, canonical_json(normalised_args(call.arguments_parsed or {}))


def tool_selection(scenario: Scenario, calls: Sequence[CallRow]) -> bool:
    distinct = {write_signature(call) for call in calls if call.attempted_write}
    got = Counter(name for name, _ in distinct)
    wanted = Counter(call.name for call in scenario.expected.tool_calls)
    return got == wanted


def arg_accuracy(
    scenario: Scenario, calls: Sequence[CallRow]
) -> tuple[float | None, dict[str, bool]]:
    """(share of expected fields right, per-field result); (None, {}) with no expected write."""
    expected = scenario.expected.tool_calls
    if not expected:
        return None, {}
    groups: dict[str, list[dict[str, object]]] = {}
    for call in expected:
        groups.setdefault(call.name, []).append(dict(call.args))
    fields: dict[str, bool] = {}
    whole_calls: list[bool] = []
    for name, wanted_calls in groups.items():
        valid = [c for c in calls if c.call_valid and c.name == name]
        recent: list[CallRow | None] = list(valid[-len(wanted_calls) :])
        padding: list[CallRow | None] = [None] * (len(wanted_calls) - len(recent))
        actual = padding + recent
        for index, (wanted, got) in enumerate(zip(wanted_calls, actual, strict=True)):
            label = name if len(wanted_calls) == 1 else f"{name}[{index}]"
            args = got.arguments_parsed or {} if got is not None else {}
            if not wanted:
                whole_calls.append(got is not None)
            for field, value in wanted.items():
                fields[f"{label}.{field}"] = (
                    got is not None and field in args and arg_matches(field, args[field], value)
                )
    results = list(fields.values()) + whole_calls
    return (sum(results) / len(results) if results else None), fields


__all__ = [
    "VALIDITY_FLAGS",
    "Validity",
    "arg_accuracy",
    "tool_selection",
    "validity",
    "write_signature",
]
