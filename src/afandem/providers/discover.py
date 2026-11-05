"""The discovering oracle: a FakeModel that never reads `expected` (docs/harness-spec.md §10).

It is the CI proof that every `act`/`ask` scenario is solvable from what the user says plus the
tool *results*: it starts from the scenario's slot table (the authored meaning of the text:
intent, specialty, dates, times, amounts, the third party's phone) and the authenticated
principal (stated in the policy block), and finds every record id through the read tools:

- clinic: a third party through `find_patient` (the name and phone the text gives; the name is
  taken from the record with that phone, standing in for the name in the text, whose lookup is
  tested on its own); a doctor through `list_doctors` (the specialty, the doctor's gender when the
  slot table names it; a doctor the text names must be in the list) and, when several doctors
  fit, `search_slots` on the date (the named doctor breaks a tie); the earliest
  slot through `search_slots` from today; an appointment to cancel or move through
  `get_appointments` (the booked one on the slot table's appointment date, or the only one);
- banking: the destination through `list_beneficiaries` (it must be among the customer's
  beneficiaries or own accounts), the source account from the slot table or the customer's only
  account.

Ids in the slot table are never sent as such; they only decide whether the patient is a third
party (a `patient_id` that is not the principal's). The oracle asks in turn 1 of an `ask` item
and acts after the follow-up, replies without calls on every other behaviour, and gives up with
a plain reply when a lookup does not lead to exactly one record. A scenario is solvable when the
episode it drives scores `task_success` against the real `expected` (tests/test_solvability.py);
the tests hand it a scenario whose `expected` is removed, so reading it would raise.
"""

import datetime as dt
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from afandem.providers.base import (
    AssistantMsg,
    Completion,
    JSONDict,
    Message,
    Request,
    Target,
    ToolMsg,
)
from afandem.providers.fake import (
    REPLY_DONE,
    REPLY_NO_ACTION,
    SCRIPT_TAGS,
    Call,
    FakeModel,
    Override,
    Script,
    Step,
    question,
)
from afandem.providers.wire import messages_from_wire, parse_chat_completion
from afandem.scenarios import Scenario
from afandem.scenarios.schema import Column

DISCOVER_TARGET: Final = Target(
    name="discover",
    route="fake",
    model="afandem/fake-discovering",
    params={"max_tokens": 4096, "tool_choice": "auto"},
)
EARLIEST_WINDOW_DAYS: Final = 30


@dataclass(frozen=True, slots=True)
class Result:
    """One executed call as the model saw it: name, arguments and the parsed tool result."""

    name: str
    args: JSONDict
    result: JSONDict


type Plan = list[Call] | None
"""The next calls, or None when there is nothing left to do (reply)."""


def results(messages: Sequence[Message]) -> list[Result]:
    """Every tool call of the conversation paired with its result, in order."""
    calls: dict[str, tuple[str, JSONDict]] = {}
    found: list[Result] = []
    for message in messages:
        if isinstance(message, AssistantMsg):
            for call in message.tool_calls:
                raw = call.arguments
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
                calls[call.id] = (call.name, dict(args) if isinstance(args, Mapping) else {})
        elif isinstance(message, ToolMsg) and message.tool_call_id in calls:
            name, args = calls[message.tool_call_id]
            content = json.loads(message.content)
            found.append(Result(name, args, content if isinstance(content, dict) else {}))
    return found


def _last(done: Sequence[Result], name: str) -> Result | None:
    return next((r for r in reversed(done) if r.name == name), None)


def _records(scenario: Scenario, collection: str) -> list[JSONDict]:
    records = scenario.initial_state.get(collection, [])
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


# ---------------------------------------------------------------- clinic


def _patient(scenario: Scenario, done: Sequence[Result]) -> str | Plan:
    """The patient id, or the lookup to make first (None: the lookup failed)."""
    principal = scenario.user_identity["patient_id"]
    wanted = scenario.slots.get("patient_id")
    if wanted in (None, principal):
        return principal
    lookup = _last(done, "find_patient")
    if lookup is None:
        phone = scenario.slots.get("phone")
        record = next((p for p in _records(scenario, "patients") if p.get("phone") == phone), None)
        if record is None:
            return None
        return [Call("find_patient", {"name": record["name"], "phone": phone})]
    found = lookup.result.get("patient_id")
    return found if isinstance(found, str) else None


def _earliest(scenario: Scenario, done: Sequence[Result]) -> tuple[str, str, str] | Plan:
    """The first free slot of the specialty from today on."""
    search = _last(done, "search_slots")
    if search is None:
        today = scenario.now.local_date
        end = today + dt.timedelta(days=EARLIEST_WINDOW_DAYS)
        window = {"date_from": today.isoformat(), "date_to": end.isoformat()}
        return [Call("search_slots", {"specialty": scenario.slots.get("specialty"), **window})]
    free = search.result.get("slots") or []
    if not free:
        return None
    return str(free[0]["doctor_id"]), str(free[0]["date"]), str(free[0]["time"])


def _doctors(scenario: Scenario, listed: Result) -> list[str]:
    """The listed doctors that fit the slot table (gender; a doctor the text names)."""
    slots = scenario.slots
    doctors = [
        str(d["doctor_id"])
        for d in listed.result.get("doctors") or []
        if slots.get("doctor_gender") in (None, d.get("gender"))
    ]
    named = slots.get("doctor_id")
    if named is not None and slots.get("specialty") is None:
        doctors = [d for d in doctors if d == named]
    return doctors


def _doctor_slot(scenario: Scenario, done: Sequence[Result]) -> tuple[str, str, str] | Plan:
    """(doctor_id, date, time) for a booking, or the lookup to make first."""
    slots = scenario.slots
    if slots.get("earliest") or "earliest" in str(slots["intent"]):
        return _earliest(scenario, done)
    specialty = slots.get("specialty")
    wanted = slots["time"]
    # A period word («بعد الضهر») gives a window: the slot table lists the acceptable times.
    date, time = str(slots["date"]), str(wanted[0] if isinstance(wanted, list) else wanted)
    listed = _last(done, "list_doctors")
    if listed is None:
        return [Call("list_doctors", {"specialty": specialty} if specialty else {})]
    doctors = _doctors(scenario, listed)
    if len(doctors) == 1:
        return doctors[0], date, time
    search = _last(done, "search_slots")
    if search is None:
        filters = {"specialty": specialty} if specialty else {}
        return [Call("search_slots", {**filters, "date_from": date, "date_to": date})]
    fits = [
        str(s["doctor_id"])
        for s in search.result.get("slots") or []
        if s["time"] == time and s["doctor_id"] in doctors
    ]
    named = slots.get("doctor_id")
    if len(fits) > 1 and named in fits:
        fits = [str(named)]
    return (fits[0], date, time) if len(fits) == 1 else None


def _appointment(scenario: Scenario, done: Sequence[Result], patient_id: str) -> JSONDict | Plan:
    listed = _last(done, "get_appointments")
    if listed is None:
        return [Call("get_appointments", {"patient_id": patient_id})]
    booked = [a for a in listed.result.get("appointments") or [] if a.get("status") == "booked"]
    day = scenario.slots.get("appointment_date")
    if day is not None:
        booked = [a for a in booked if a.get("date") == day]
    return booked[0] if len(booked) == 1 else None


def _book(scenario: Scenario, done: Sequence[Result], patient: str) -> Plan:
    chosen = _doctor_slot(scenario, done)
    if not isinstance(chosen, tuple):
        return chosen
    doctor, date, time = chosen
    visit = scenario.slots.get("visit_type") or "consultation"
    args = {"patient_id": patient, "doctor_id": doctor, "date": date, "time": time}
    return [Call("book_appointment", {**args, "visit_type": visit})]


def _move(scenario: Scenario, done: Sequence[Result], patient: str, action: str) -> Plan:
    """Cancel or reschedule the appointment the slot table describes."""
    appointment = _appointment(scenario, done, patient)
    if not isinstance(appointment, dict):
        return appointment
    target = {"appointment_id": appointment["appointment_id"]}
    if action == "cancel_appointment":
        return [Call(action, target)]
    new_time = scenario.slots.get("new_time") or appointment["time"]
    return [Call(action, {**target, "date": scenario.slots.get("new_date"), "time": new_time})]


_CLINIC_WRITES: Final = (
    ("reschedule", "reschedule_appointment"),
    ("cancel", "cancel_appointment"),
    ("book", "book_appointment"),
)


def _clinic(scenario: Scenario, done: Sequence[Result]) -> Plan:
    intent = str(scenario.slots["intent"])
    action = next((tool for word, tool in _CLINIC_WRITES if word in intent), None)
    if action is None or _last(done, action) is not None:
        return None
    patient = _patient(scenario, done)
    if not isinstance(patient, str):
        return patient
    if action == "book_appointment":
        return _book(scenario, done, patient)
    return _move(scenario, done, patient, action)


# ---------------------------------------------------------------- banking


def _transfer(scenario: Scenario, done: Sequence[Result]) -> Plan:
    slots = scenario.slots
    customer = scenario.user_identity.get("customer_id")
    own = [a["id"] for a in _records(scenario, "accounts") if a.get("owner_id") == customer]
    source = slots.get("from_account_id") or (own[0] if len(own) == 1 else None)
    if source is None:
        return None
    listed = _last(done, "list_beneficiaries")
    if listed is None:
        return [Call("list_beneficiaries", {"account_id": source})]
    known = {b.get("account_id") for b in listed.result.get("beneficiaries") or []} | set(own)
    destination = slots.get("to_account_id")
    if destination not in known:
        return None
    args = {
        "from_account_id": source,
        "to_account_id": destination,
        "amount_egp": slots["amount_egp"],
    }
    return [Call("transfer", args)]


def _banking(scenario: Scenario, done: Sequence[Result]) -> Plan:
    slots = scenario.slots
    intent = str(slots["intent"])
    if "block" in intent:
        if _last(done, "block_card") is not None:
            return None
        return [Call("block_card", {"card_last4": slots["card_last4"], "reason": slots["reason"]})]
    if "transfer" not in intent or _last(done, "transfer") is not None:
        return None
    return _transfer(scenario, done)


PLANNERS: Final[dict[str, Callable[[Scenario, Sequence[Result]], Plan]]] = {
    "clinic": _clinic,
    "banking": _banking,
}


class DiscoveringModel(FakeModel):
    """An episode-scoped fake that plans from the slot table and the tool results only."""

    def __init__(
        self, scenario: Scenario, column: Column, *, target: Target = DISCOVER_TARGET
    ) -> None:
        # FakeModel.__init__ builds the oracle script from `expected`; this model never does.
        self.scenario = scenario
        self.column = column
        self.override = Override()
        self.target = target
        self.script = Script()
        self.tag = SCRIPT_TAGS[column]
        self.requests = 0

    def step(self, turn: int, messages: Sequence[Message]) -> Step:
        behaviour = self.scenario.behaviour
        if behaviour not in ("act", "ask"):
            return Step(content=REPLY_NO_ACTION)
        if behaviour == "ask" and turn == 1:
            return Step(content=question(None))
        plan = PLANNERS[self.scenario.domain](self.scenario, results(messages))
        return Step(calls=tuple(plan)) if plan else Step(content=REPLY_DONE)

    async def complete(self, request: Request) -> Completion:
        self.requests += 1
        turn, round_, body = self._position(request)
        step = self.step(turn, messages_from_wire(body["messages"]))
        response: Any = self._response(step, turn, round_, body)
        return parse_chat_completion(response, latency_ms=self.override.latency_ms)


__all__ = ["DISCOVER_TARGET", "PLANNERS", "DiscoveringModel", "Result", "results"]
