"""FakeModel: an offline, scenario-aware provider for CI and tests (docs/harness-spec.md §10).

An **oracle by default** that goes through the real converter: every request is turned into the
wire body (`wire.request_body`), read back (`wire.messages_from_wire`), answered with an
OpenAI-shaped response body and parsed by `wire.parse_chat_completion`, so the converter paths
run without keys or network.

The fake is episode-scoped (`fake_factory` builds one per scenario and column) and stateless
across requests: it reads its position from the conversation (turn = number of user messages,
round = assistant messages since the last one), so a retried or replayed request gets the same
answer. Oracle per behaviour:

- `act`: the expected writes (first value of any acceptable-value list) in round 1, then a
  reply; a clinic write on another patient's record is preceded, in the same round, by the
  `find_patient` call (name and phone from the state) that the third-party rule requires;
- `ask`: turn 1 a clarifying question (no call); after the follow-up the writes, then a reply;
- `inform`: the `read_calls`, then a reply containing `str(answer_must_contain[0].value)`;
- `none`, `refuse`, `out_of_scope`: a reply, no calls.

Reply texts are neutral placeholders (`[fake] done`), never natural utterances.

Overrides (a JSON file or a dict) script failure modes and near-misses. Keys, most specific
first: `"<scenario_id>|<column>"`, `"<scenario_id>"`, `"*|<column>"`, `"*"`; a value is a mode
name or `{"mode": <mode>, "latency_ms": <int>}`. Modes:

- `oracle` (default);
- `invented_tool`: an unknown tool called first (flag `invented_tool` on the call);
- `arabic_keys`: the first write's keys get an Arabic letter (`arabic_keys`, `schema_invalid`);
- `arabic_indic_digits`: the first write's ASCII digits become Arabic-Indic (`non_ascii_digits`);
- `parallel_calls`: a harmless read joins the first call round (several calls in one completion);
- `question_and_write`: turn 1 asks and writes in the same completion;
- `english_reply`: replies carry an `[fake en]` marker (for the reply-language scorer, (c));
- `length_mid_call`: the first completion stops with `length` inside a tool call (half its
  arguments; flags `length`, `truncated_tool_call`), or with a clipped reply when the item has no
  call;
- `empty_reply`: turn 1 is an empty reply (flag `empty_reply`); the oracle acts after the
  follow-up when one is due;
- `error_200`: an HTTP-200 body with an `error` object -> `ProviderOutcomeError("provider_error")`;
- `http_403`: `ProviderOutcomeError("blocked_by_provider", status=403)`;
- `quota`: `ProviderOutcomeError("quota", status=429)`;
- `invalid_loop`: two schema-invalid calls to the same tool (flag `invalid_loop`);
- `hallucinated_action`: claims done in every turn, never calls;
- `hallucinated_then_recover`: claims done in turn 1, acts after the confirmation;
- `round_cap`: harmless reads forever (flag `round_cap_hit`);
- near-misses the scorer must fail: `near_miss_date` (every write date + 1 day),
  `near_miss_id` (the first of doctor/account/appointment/patient id swapped for another record
  of the same kind), `near_miss_phone_digits` (Arabic-Indic digits in a phone argument).

A mode that cannot apply to a scenario (a near-miss with no such argument, a write mode on an
item without writes) raises `OverrideNotApplicableError` when the fake is built.
"""

import copy
import datetime as dt
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from afandem.providers.base import (
    AssistantMsg,
    Completion,
    FailureOutcome,
    JSONDict,
    Provider,
    ProviderOutcomeError,
    Request,
    Target,
    UserMsg,
    canonical_json,
)
from afandem.providers.wire import EmbeddedError, messages_from_wire, parse_chat_completion
from afandem.providers.wire import request_body as wire_request_body
from afandem.scenarios import Scenario
from afandem.scenarios.schema import Column

Mode = Literal[
    "oracle",
    "invented_tool",
    "arabic_keys",
    "arabic_indic_digits",
    "parallel_calls",
    "question_and_write",
    "english_reply",
    "length_mid_call",
    "empty_reply",
    "error_200",
    "http_403",
    "quota",
    "invalid_loop",
    "hallucinated_action",
    "hallucinated_then_recover",
    "round_cap",
    "near_miss_date",
    "near_miss_id",
    "near_miss_phone_digits",
]
MODES: Final[tuple[Mode, ...]] = get_args(Mode)
NEAR_MISSES: Final[tuple[Mode, ...]] = ("near_miss_date", "near_miss_id", "near_miss_phone_digits")

FAKE_TARGET: Final = Target(
    name="fake",
    route="fake",
    model="afandem/fake-oracle",
    params={"max_tokens": 4096, "tool_choice": "auto"},
)
FAKE_FINGERPRINT: Final = "fake-1"
INVENTED_TOOL: Final = "fake_invented_tool"
DEFAULT_LATENCY_MS: Final = 1

REPLY_DONE: Final = "[fake] done"
REPLY_QUESTION: Final = "[fake] question"
REPLY_NO_ACTION: Final = "[fake] reply"
REPLY_CLIPPED: Final = "[fake] clipped"
EN_MARKER: Final = "[fake en]"

_ALEF: Final = "\N{ARABIC LETTER ALEF}"
_TO_ARABIC_INDIC: Final = {ord("0") + i: 0x0660 + i for i in range(10)}
_ID_SWAPS: Final = ("doctor_id", "to_account_id", "account_id", "appointment_id", "patient_id")


class OverrideNotApplicableError(ValueError):
    """An override mode that has nothing to act on in this scenario."""


class Override(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Mode = "oracle"
    latency_ms: int = Field(default=DEFAULT_LATENCY_MS, ge=0)


type Overrides = Mapping[str, Override]


def load_overrides(source: Path | Mapping[str, Any] | None) -> dict[str, Override]:
    """Read overrides from a JSON file or a dict (see the module docstring for the keys)."""
    if source is None:
        return {}
    raw: object = (
        json.loads(source.read_text(encoding="utf-8")) if isinstance(source, Path) else source
    )
    if not isinstance(raw, Mapping):
        raise ValueError("overrides must be a JSON object keyed by scenario id, column or '*'")
    out: dict[str, Override] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"override key {key!r} is not a string")
        spec = {"mode": value} if isinstance(value, str) else value
        out[key] = Override.model_validate(spec)
    return out


def override_for(overrides: Overrides, scenario_id: str, column: str) -> Override:
    for key in (f"{scenario_id}|{column}", scenario_id, f"*|{column}", "*"):
        if key in overrides:
            return overrides[key]
    return Override()


# ---------------------------------------------------------------- scripts


@dataclass(frozen=True)
class Call:
    name: str
    args: str | JSONDict
    """A dict is sent as JSON; a string is sent verbatim (malformed or truncated arguments)."""

    def wire_arguments(self) -> str:
        if isinstance(self.args, str):
            return self.args
        return json.dumps(self.args, ensure_ascii=False)


@dataclass(frozen=True)
class Step:
    """One scripted completion."""

    content: str | None = None
    calls: tuple[Call, ...] = ()
    finish: str | None = None
    """Raw finish reason; None = `tool_calls` with calls, else `stop`."""
    fail: FailureOutcome | None = None
    status: int | None = None
    embedded_error: bool = False

    def finish_reason(self) -> str:
        if self.finish is not None:
            return self.finish
        return "tool_calls" if self.calls else "stop"


@dataclass
class Script:
    turns: dict[int, list[Step]] = field(default_factory=dict)

    def step(self, turn: int, round_: int) -> Step:
        steps = self.turns.get(turn, [])
        return steps[round_] if round_ < len(steps) else Step(content=REPLY_DONE)


def _first_values(args: Mapping[str, Any]) -> JSONDict:
    """Acceptable-value lists -> their first value."""
    return {
        key: (copy.deepcopy(value[0]) if isinstance(value, list) and value else value)
        for key, value in args.items()
    }


def _records(scenario: Scenario, collection: str) -> list[JSONDict]:
    records = scenario.initial_state.get(collection, [])
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def _prerequisites(scenario: Scenario, writes: list[Call]) -> list[Call]:
    """`find_patient` (name and phone) for clinic writes on another patient's record."""
    if scenario.domain != "clinic":
        return []
    principal = scenario.user_identity.get("patient_id")
    patients = {r.get("id"): r for r in _records(scenario, "patients")}
    appointments = {r.get("id"): r for r in _records(scenario, "appointments")}
    found: list[Call] = []
    for call in writes:
        args = call.args if isinstance(call.args, dict) else {}
        patient_id = args.get("patient_id")
        if patient_id is None and "appointment_id" in args:
            patient_id = appointments.get(args["appointment_id"], {}).get("patient_id")
        patient = patients.get(patient_id)
        if patient_id == principal or patient is None or not patient.get("phone"):
            continue
        lookup = Call("find_patient", {"name": patient["name"], "phone": patient["phone"]})
        if lookup not in found:
            found.append(lookup)
    return found


def _harmless_read(scenario: Scenario) -> Call:
    if scenario.domain == "banking":
        customer = scenario.user_identity.get("customer_id")
        own = [r["id"] for r in _records(scenario, "accounts") if r.get("owner_id") == customer]
        return Call("get_balance", {"account_id": own[0] if own else ""})
    return Call("list_doctors", {})


def oracle_script(scenario: Scenario) -> Script:
    expected = scenario.expected
    writes = [Call(c.name, _first_values(c.args)) for c in expected.tool_calls]
    act_round = Step(calls=tuple(_prerequisites(scenario, writes) + writes))
    match scenario.behaviour:
        case "act":
            return Script({1: [act_round, Step(content=REPLY_DONE)]})
        case "ask":
            return Script(
                {1: [Step(content=REPLY_QUESTION)], 2: [act_round, Step(content=REPLY_DONE)]}
            )
        case "inform":
            reads = tuple(Call(c.name, _first_values(c.args)) for c in expected.read_calls or [])
            answers = expected.answer_must_contain or []
            answer = f"[fake] answer {answers[0].value}" if answers else REPLY_DONE
            return Script({1: [Step(calls=reads), Step(content=answer)]})
        case _:
            return Script({1: [Step(content=REPLY_NO_ACTION)]})


def _write_steps(script: Script) -> list[tuple[int, int]]:
    """(turn, index) of every scripted step that carries calls."""
    return [
        (turn, index)
        for turn, steps in sorted(script.turns.items())
        for index, step in enumerate(steps)
        if step.calls
    ]


def _map_calls(
    scenario: Scenario, script: Script, change: Callable[[Call], Call | None], mode: Mode
) -> Script:
    """Apply `change` to every scripted call; it returns None when it does not apply."""
    applied = False
    out = Script({turn: list(steps) for turn, steps in script.turns.items()})
    for turn, index in _write_steps(out):
        step = out.turns[turn][index]
        calls = []
        for call in step.calls:
            changed = change(call)
            applied = applied or changed is not None
            calls.append(changed if changed is not None else call)
        out.turns[turn][index] = replace(step, calls=tuple(calls))
    if not applied:
        raise OverrideNotApplicableError(f"{mode} does not apply to {scenario.id}")
    return out


def _writes_only(scenario: Scenario) -> Callable[[Call], bool]:
    names = {c.name for c in scenario.expected.tool_calls}
    return lambda call: call.name in names


def _shift_dates(call: Call) -> Call | None:
    if not isinstance(call.args, dict):
        return None
    args = dict(call.args)
    changed = False
    for key, value in args.items():
        if "date" in key and isinstance(value, str):
            args[key] = (dt.date.fromisoformat(value) + dt.timedelta(days=1)).isoformat()
            changed = True
    return replace(call, args=args) if changed else None


def _id_pool(scenario: Scenario, key: str) -> list[str]:
    if key == "doctor_id":
        return [r["id"] for r in _records(scenario, "doctors")]
    if key == "patient_id":
        return [r["id"] for r in _records(scenario, "patients")]
    if key == "appointment_id":
        return [r["id"] for r in _records(scenario, "appointments")]
    customer = scenario.user_identity.get("customer_id")
    if key == "to_account_id":
        pool = [
            r["account_id"]
            for r in _records(scenario, "beneficiaries")
            if r.get("owner_id") == customer
        ]
        return pool or [r["id"] for r in _records(scenario, "accounts")]
    return [r["id"] for r in _records(scenario, "accounts") if r.get("owner_id") == customer]


def _swap_id(scenario: Scenario) -> Callable[[Call], Call | None]:
    def change(call: Call) -> Call | None:
        if not isinstance(call.args, dict):
            return None
        for key in _ID_SWAPS:
            value = call.args.get(key)
            if isinstance(value, str):
                others = sorted(i for i in _id_pool(scenario, key) if i != value)
                wrong = others[0] if others else f"{value}_wrong"
                return replace(call, args={**call.args, key: wrong})
        return None

    return change


def _to_arabic_indic(value: object) -> object:
    if isinstance(value, str):
        return value.translate(_TO_ARABIC_INDIC)
    if isinstance(value, dict):
        return {k: _to_arabic_indic(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_arabic_indic(v) for v in value]
    return value


def _phone_digits(call: Call) -> Call | None:
    if not isinstance(call.args, dict) or not isinstance(call.args.get("phone"), str):
        return None
    return replace(call, args={**call.args, "phone": _to_arabic_indic(call.args["phone"])})


def _first_write(
    scenario: Scenario, change: Callable[[JSONDict], JSONDict]
) -> Callable[[Call], Call | None]:
    is_write = _writes_only(scenario)
    done: list[bool] = []

    def apply(call: Call) -> Call | None:
        if done or not is_write(call) or not isinstance(call.args, dict):
            return None
        done.append(True)
        return replace(call, args=change(call.args))

    return apply


def _require_calls(scenario: Scenario, script: Script, mode: Mode) -> tuple[int, int]:
    steps = _write_steps(script)
    if not steps:
        raise OverrideNotApplicableError(f"{mode} needs a scripted call; {scenario.id} has none")
    return steps[0]


def _only_writes(
    scenario: Scenario, change: Callable[[Call], Call | None]
) -> Callable[[Call], Call | None]:
    is_write = _writes_only(scenario)
    return lambda call: change(call) if is_write(call) else None


type Transform = Callable[[Scenario, Script], Script]


def _invented_tool(scenario: Scenario, script: Script) -> Script:
    script.turns[1] = [Step(calls=(Call(INVENTED_TOOL, {}),)), *script.turns[1]]
    return script


def _arabic_keys(scenario: Scenario, script: Script) -> Script:
    rename = _first_write(scenario, lambda args: {_ALEF + k: v for k, v in args.items()})
    return _map_calls(scenario, script, rename, "arabic_keys")


def _arabic_indic_digits(scenario: Scenario, script: Script) -> Script:
    digits = _first_write(scenario, lambda args: {k: _to_arabic_indic(v) for k, v in args.items()})
    return _map_calls(scenario, script, digits, "arabic_indic_digits")


def _parallel_calls(scenario: Scenario, script: Script) -> Script:
    turn, index = _require_calls(scenario, script, "parallel_calls")
    step = script.turns[turn][index]
    script.turns[turn][index] = replace(step, calls=(_harmless_read(scenario), *step.calls))
    return script


def _question_and_write(scenario: Scenario, script: Script) -> Script:
    if scenario.behaviour not in ("act", "ask"):
        raise OverrideNotApplicableError("question_and_write needs an act or ask item")
    turn, index = _require_calls(scenario, script, "question_and_write")
    writes = script.turns[turn][index]
    return Script({1: [replace(writes, content=REPLY_QUESTION), Step(content=REPLY_QUESTION)]})


def _english_reply(scenario: Scenario, script: Script) -> Script:
    for steps in script.turns.values():
        steps[:] = [
            replace(s, content=f"{EN_MARKER} {s.content}") if s.content else s for s in steps
        ]
    return script


def _length_mid_call(scenario: Scenario, script: Script) -> Script:
    first = script.turns[1][0]
    if not first.calls:
        return Script({1: [Step(content=REPLY_CLIPPED, finish="length")]})
    call = first.calls[0]
    text = call.wire_arguments()
    truncated = Call(call.name, text[: max(1, len(text) // 2)])
    return Script({1: [Step(calls=(truncated,), finish="length")]})


def _empty_reply(scenario: Scenario, script: Script) -> Script:
    later = script.turns.get(2) or (script.turns[1] if scenario.behaviour == "act" else [])
    return Script({1: [Step(content=None)], 2: later})


def _failure(outcome: FailureOutcome, status: int, *, embedded: bool = False) -> Transform:
    return lambda scenario, script: Script(
        {1: [Step(fail=outcome, status=status, embedded_error=embedded)]}
    )


def _invalid_loop(scenario: Scenario, script: Script) -> Script:
    names = [c.name for c in scenario.expected.tool_calls] or [
        c.name for c in scenario.expected.read_calls or []
    ]
    name = names[0] if names else _harmless_read(scenario).name
    bad = Step(calls=(Call(name, {"unexpected_field": 1}),))
    return Script({1: [bad, bad]})


def _hallucinated_action(scenario: Scenario, script: Script) -> Script:
    return Script({1: [Step(content=REPLY_DONE)], 2: [Step(content=REPLY_DONE)]})


def _hallucinated_then_recover(scenario: Scenario, script: Script) -> Script:
    if scenario.behaviour != "act":
        raise OverrideNotApplicableError("hallucinated_then_recover needs an act item")
    return Script({1: [Step(content=REPLY_DONE)], 2: script.turns[1]})


def _round_cap(scenario: Scenario, script: Script) -> Script:
    return Script({1: [Step(calls=(_harmless_read(scenario),))] * 12})


def _near_miss_date(scenario: Scenario, script: Script) -> Script:
    return _map_calls(scenario, script, _only_writes(scenario, _shift_dates), "near_miss_date")


def _near_miss_id(scenario: Scenario, script: Script) -> Script:
    swap = _only_writes(scenario, _swap_id(scenario))
    return _map_calls(scenario, script, swap, "near_miss_id")


def _near_miss_phone_digits(scenario: Scenario, script: Script) -> Script:
    return _map_calls(scenario, script, _phone_digits, "near_miss_phone_digits")


_TRANSFORMS: Final[dict[Mode, Transform]] = {
    "oracle": lambda scenario, script: script,
    "invented_tool": _invented_tool,
    "arabic_keys": _arabic_keys,
    "arabic_indic_digits": _arabic_indic_digits,
    "parallel_calls": _parallel_calls,
    "question_and_write": _question_and_write,
    "english_reply": _english_reply,
    "length_mid_call": _length_mid_call,
    "empty_reply": _empty_reply,
    "error_200": _failure("provider_error", 200, embedded=True),
    "http_403": _failure("blocked_by_provider", 403),
    "quota": _failure("quota", 429),
    "invalid_loop": _invalid_loop,
    "hallucinated_action": _hallucinated_action,
    "hallucinated_then_recover": _hallucinated_then_recover,
    "round_cap": _round_cap,
    "near_miss_date": _near_miss_date,
    "near_miss_id": _near_miss_id,
    "near_miss_phone_digits": _near_miss_phone_digits,
}


def build_script(scenario: Scenario, mode: Mode) -> Script:
    """The scripted completions of one episode under `mode`."""
    return _TRANSFORMS[mode](scenario, oracle_script(scenario))


# ---------------------------------------------------------------- provider


class FakeModel:
    """An episode-scoped fake provider for one scenario and column."""

    def __init__(
        self,
        scenario: Scenario,
        column: Column,
        override: Override | None = None,
        *,
        target: Target = FAKE_TARGET,
    ) -> None:
        self.scenario = scenario
        self.column = column
        self.override = override or Override()
        self.target = target
        self.script = build_script(scenario, self.override.mode)
        self.requests = 0

    def _position(self, request: Request) -> tuple[int, int, JSONDict]:
        body = wire_request_body(request)
        if not body.get("tools"):
            raise ValueError("fake model: the request carries no tools")
        messages = messages_from_wire(body["messages"])
        turn = sum(isinstance(m, UserMsg) for m in messages)
        last_user = max(i for i, m in enumerate(messages) if isinstance(m, UserMsg))
        round_ = sum(isinstance(m, AssistantMsg) for m in messages[last_user:])
        return turn, round_, body

    def _response(self, step: Step, turn: int, round_: int, body: JSONDict) -> JSONDict:
        message: JSONDict = {"role": "assistant", "content": step.content}
        if step.calls:
            message["tool_calls"] = [
                {
                    "id": f"call_{turn}_{round_ + 1}_{index}",
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.wire_arguments()},
                }
                for index, call in enumerate(step.calls)
            ]
        prompt_tokens = len(canonical_json(body)) // 4
        completion_tokens = max(1, len(canonical_json(message)) // 4)
        return {
            "id": f"fake-{self.scenario.id}-{self.column}-{turn}-{round_ + 1}",
            "object": "chat.completion",
            "created": 0,
            "model": self.target.model,
            "system_fingerprint": FAKE_FINGERPRINT,
            "provider": "fake",
            "choices": [{"index": 0, "message": message, "finish_reason": step.finish_reason()}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    async def complete(self, request: Request) -> Completion:
        self.requests += 1
        turn, round_, body = self._position(request)
        step = self.script.step(turn, round_)
        if step.fail is not None and not step.embedded_error:
            raise ProviderOutcomeError(
                step.fail, f"fake {step.fail} (HTTP {step.status})", status=step.status
            )
        if step.embedded_error:
            response: JSONDict = {"error": {"code": 500, "message": "fake embedded error"}}
        else:
            response = self._response(step, turn, round_, body)
        try:
            return parse_chat_completion(response, latency_ms=self.override.latency_ms)
        except EmbeddedError as exc:
            raise ProviderOutcomeError(
                "provider_error", f"error inside HTTP 200: {exc}", status=200, body=exc.body
            ) from exc


type ProviderFactory = Callable[[Scenario, Column, int], Provider]


def fake_factory(
    overrides: Overrides | None = None,
    *,
    wrap: Callable[[Provider], Provider] | None = None,
    target: Target = FAKE_TARGET,
) -> ProviderFactory:
    """A factory of episode-scoped fakes; `wrap` adds layers (e.g. `BudgetedProvider`)."""
    table = overrides or {}

    def make(scenario: Scenario, column: Column, repeat: int = 1) -> Provider:
        del repeat  # the oracle is deterministic; repeats differ only through overrides
        fake: Provider = FakeModel(
            scenario, column, override_for(table, scenario.id, column), target=target
        )
        return wrap(fake) if wrap is not None else fake

    return make


__all__ = [
    "FAKE_TARGET",
    "MODES",
    "NEAR_MISSES",
    "FakeModel",
    "Mode",
    "Override",
    "OverrideNotApplicableError",
    "ProviderFactory",
    "Script",
    "Step",
    "build_script",
    "fake_factory",
    "load_overrides",
    "oracle_script",
    "override_for",
]
