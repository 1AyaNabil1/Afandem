"""The discovering oracle: a FakeModel that never reads `expected` (docs/harness-spec.md §10).

It is the proof (tests/test_solvability.py in CI, and the `solvability` rule of
`afandem data lint`) that every `act`, `ask` and `inform` scenario is solvable from what the user
says plus the tool *results*: it starts from the scenario's slot table (the authored meaning of
the text: intent, specialty, dates, times, amounts, the third party's or beneficiary's phone) and
what the policy block states (the authenticated principal; in banking also the customer's own
accounts and cards, decision D23), and finds every other record id through the read tools:

- clinic: a third party through `find_patient` (the name and phone the text gives; the name is
  taken from the record with that phone, standing in for the name in the text, whose lookup is
  tested on its own); a doctor through `list_doctors` (the specialty, the doctor's gender when the
  slot table names it; a doctor the text names must be in the list) and, when several doctors
  fit, `search_slots` on the date (the named doctor breaks a tie); the earliest
  slot through `search_slots` from today; an appointment to cancel or move through
  `get_appointments` (the booked one on the slot table's appointment date, or the only one);
- banking: a beneficiary through `list_beneficiaries` with the phone the text gives (slot
  `phone`), else with the beneficiary's name (taken, as in clinic, from the customer's
  beneficiary record for the slot table's `to_account_id`), else from the full list (an account
  number the text gives must be on it); a transfer to another of the customer's own accounts
  needs no lookup. The source account is the slot table's or the customer's only account, and
  the card to block the slot table's `card_last4` or the customer's only card.

Ids in the slot table are sent only when the policy block states them (the principal, banking's
own accounts and cards); the others only decide whether the patient is a third party and which
record's name stands in for the text. On an `inform` item the oracle makes the reads the slot
table points to (clinic: `get_appointments` for a patient or an appointment, `list_doctors` for a
specialty or a doctor, `search_slots` for the earliest slot; banking: `list_transactions`,
`list_beneficiaries` or `get_balance` by the intent's wording, on the slot table's account or
the only one) and answers with the read results verbatim, so the scorer finds the answer only
if a tool returned it. It asks in turn 1 of an `ask` item and acts after the follow-up, replies
without calls on `none`, `refuse` and `out_of_scope`, and gives up with a plain reply when a
lookup does not lead to exactly one record.

`solve` drives one offline episode with it on the scenario with `expected` removed (so reading
it would raise) and scores the episode against the real `expected`: the scenario is solvable
when that scores `task_success`.
"""

import datetime as dt
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from afandem.agent.loop import Episode, run_episode
from afandem.agent.prompts import PromptSet
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
from afandem.scoring import Scores, score_episode

DISCOVER_TARGET: Final = Target(
    name="discover",
    route="fake",
    model="afandem/fake-discovering",
    params={"max_tokens": 4096, "tool_choice": "auto"},
)
EARLIEST_WINDOW_DAYS: Final = 30
TRANSACTIONS_WINDOW_DAYS: Final = 30
REPLY_ANSWER: Final = "[fake] answer"
PATIENT_KEYS: Final = ("patient_id", "appointment_id", "appointment_date")
DOCTOR_KEYS: Final = ("specialty", "doctor_id", "doctor_gender")
BANKING_READS: Final = (
    ("beneficiar", "list_beneficiaries"),
    ("transaction", "list_transactions"),
    ("transfer", "list_transactions"),
    ("statement", "list_transactions"),
)
"""Intent words that pick a banking read; any other inform intent reads the balance."""


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


def _pending(wanted: Sequence[Call], done: Sequence[Result]) -> Plan:
    """The wanted calls not made yet; None once every one has been made."""
    made = [(r.name, r.args) for r in done]
    return [call for call in wanted if (call.name, call.args) not in made] or None


def answer(done: Sequence[Result]) -> str:
    """The inform reply: every read result verbatim."""
    return f"{REPLY_ANSWER} {json.dumps([r.result for r in done], ensure_ascii=False)}"


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


def _earliest_search(scenario: Scenario) -> Call:
    today = scenario.now.local_date
    end = today + dt.timedelta(days=EARLIEST_WINDOW_DAYS)
    window = {"date_from": today.isoformat(), "date_to": end.isoformat()}
    return Call("search_slots", {"specialty": scenario.slots.get("specialty"), **window})


def _earliest(scenario: Scenario, done: Sequence[Result]) -> tuple[str, str, str] | Plan:
    """The first free slot of the specialty from today on."""
    search = _last(done, "search_slots")
    if search is None:
        return [_earliest_search(scenario)]
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
    date, time = str(slots["date"]), str(slots["time"])
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


def _clinic_reads(scenario: Scenario, done: Sequence[Result]) -> Plan:
    """The reads an `inform` item's slot table points to (a patient's appointments, the doctors,
    the earliest slots), after the third party's lookup when there is one."""
    slots = scenario.slots
    wanted: list[Call] = []
    if any(key in slots for key in PATIENT_KEYS):
        patient = _patient(scenario, done)
        if not isinstance(patient, str):
            return patient
        wanted.append(Call("get_appointments", {"patient_id": patient}))
    if slots.get("earliest") or "earliest" in str(slots["intent"]):
        wanted.append(_earliest_search(scenario))
    if any(key in slots for key in DOCTOR_KEYS) or "doctor" in str(slots["intent"]):
        specialty = slots.get("specialty")
        wanted.append(Call("list_doctors", {"specialty": specialty} if specialty else {}))
    return _pending(wanted, done)


# ---------------------------------------------------------------- banking


def _own_accounts(scenario: Scenario) -> list[str]:
    """The customer's accounts, as the policy block lists them (D23)."""
    customer = scenario.user_identity.get("customer_id")
    accounts = _records(scenario, "accounts")
    return [str(a["id"]) for a in accounts if a.get("owner_id") == customer]


def _account(scenario: Scenario, *keys: str) -> str | None:
    """The account the slot table names under the first of `keys`, else the only own one."""
    for key in keys:
        named = scenario.slots.get(key)
        if isinstance(named, str):
            return named
    own = _own_accounts(scenario)
    return own[0] if len(own) == 1 else None


def _beneficiary_query(scenario: Scenario) -> JSONDict | None:
    """What the text gives to find the beneficiary: the phone, else the name (from the customer's
    beneficiary record for the slot table's destination); None when it gives neither."""
    slots = scenario.slots
    phone = slots.get("phone")
    if isinstance(phone, str):
        return {"phone": phone}
    customer = scenario.user_identity.get("customer_id")
    record = next(
        (
            b
            for b in _records(scenario, "beneficiaries")
            if b.get("owner_id") == customer and b.get("account_id") == slots.get("to_account_id")
        ),
        None,
    )
    return {"name": record["name"]} if record is not None else None


def _destination(scenario: Scenario, done: Sequence[Result], source: str) -> str | Plan:
    """The account to transfer to, or the lookup to make first (None: no single one found)."""
    wanted = scenario.slots.get("to_account_id")
    if isinstance(wanted, str) and wanted in _own_accounts(scenario):
        return wanted
    query = _beneficiary_query(scenario)
    listed = _last(done, "list_beneficiaries")
    if listed is None:
        return [Call("list_beneficiaries", {"account_id": source, **(query or {})})]
    found = [str(b.get("account_id")) for b in listed.result.get("beneficiaries") or []]
    if query is None:
        return wanted if isinstance(wanted, str) and wanted in found else None
    return found[0] if len(found) == 1 else None


def _transfer(scenario: Scenario, done: Sequence[Result]) -> Plan:
    source = _account(scenario, "from_account_id")
    amount = scenario.slots.get("amount_egp")
    if source is None or not isinstance(amount, int):
        return None
    destination = _destination(scenario, done, source)
    if not isinstance(destination, str):
        return destination
    args = {"from_account_id": source, "to_account_id": destination, "amount_egp": amount}
    return [Call("transfer", args)]


def _block(scenario: Scenario, done: Sequence[Result]) -> Plan:
    if _last(done, "block_card") is not None:
        return None
    own = _own_accounts(scenario)
    cards = [str(c["last4"]) for c in _records(scenario, "cards") if c.get("account_id") in own]
    card = scenario.slots.get("card_last4") or (cards[0] if len(cards) == 1 else None)
    reason = scenario.slots.get("reason")
    if card is None or reason is None:
        return None
    return [Call("block_card", {"card_last4": card, "reason": reason})]


def _banking(scenario: Scenario, done: Sequence[Result]) -> Plan:
    intent = str(scenario.slots["intent"])
    if "block" in intent:
        return _block(scenario, done)
    if "transfer" not in intent or _last(done, "transfer") is not None:
        return None
    return _transfer(scenario, done)


def _transactions_window(scenario: Scenario) -> JSONDict:
    """The slot table's dates (`date_from`/`date_to`, or one `date`), else the last 30 days."""
    slots = scenario.slots
    today = scenario.now.local_date
    start = slots.get("date_from") or slots.get("date")
    end = slots.get("date_to") or slots.get("date")
    default_start = today - dt.timedelta(days=TRANSACTIONS_WINDOW_DAYS)
    return {
        "date_from": str(start) if start else default_start.isoformat(),
        "date_to": str(end) if end else today.isoformat(),
    }


def _banking_reads(scenario: Scenario, done: Sequence[Result]) -> Plan:
    account = _account(scenario, "account_id", "from_account_id")
    if account is None:
        return None
    intent = str(scenario.slots["intent"])
    tool = next((tool for word, tool in BANKING_READS if word in intent), "get_balance")
    args: JSONDict = {"account_id": account}
    if tool == "list_transactions":
        args.update(_transactions_window(scenario))
    return _pending([Call(tool, args)], done)


PLANNERS: Final[dict[str, Callable[[Scenario, Sequence[Result]], Plan]]] = {
    "clinic": _clinic,
    "banking": _banking,
}
"""The writes of an `act` or `ask` item, one round at a time."""
READERS: Final[dict[str, Callable[[Scenario, Sequence[Result]], Plan]]] = {
    "clinic": _clinic_reads,
    "banking": _banking_reads,
}
"""The reads of an `inform` item."""


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
        scenario, done = self.scenario, results(messages)
        if scenario.behaviour == "inform":
            reads = READERS[scenario.domain](scenario, done)
            return Step(calls=tuple(reads)) if reads else Step(content=answer(done))
        if scenario.behaviour not in ("act", "ask"):
            return Step(content=REPLY_NO_ACTION)
        if scenario.behaviour == "ask" and turn == 1:
            return Step(content=question(None))
        plan = PLANNERS[scenario.domain](scenario, done)
        return Step(calls=tuple(plan)) if plan else Step(content=REPLY_DONE)

    async def complete(self, request: Request) -> Completion:
        self.requests += 1
        turn, round_, body = self._position(request)
        step = self.step(turn, messages_from_wire(body["messages"]))
        response: Any = self._response(step, turn, round_, body)
        return parse_chat_completion(response, latency_ms=self.override.latency_ms)


def blinded(scenario: Scenario) -> Scenario:
    """The scenario without `expected`: any read of it by the oracle raises."""
    return scenario.model_copy(update={"expected": None})


async def solve(
    scenario: Scenario, column: Column = "egy", *, model_view: Scenario | None = None
) -> tuple[Episode, Scores]:
    """One offline episode of the oracle on `model_view` (default: the blinded scenario), scored
    against the real `expected`. The oracle ignores the text, so the column only tags replies."""
    model = DiscoveringModel(model_view or blinded(scenario), column)
    prompt = PromptSet.stub().render(scenario)
    episode = await run_episode(
        scenario, column, model, target=DISCOVER_TARGET, system_prompt=prompt
    )
    return episode, score_episode(scenario, episode)


__all__ = [
    "DISCOVER_TARGET",
    "PLANNERS",
    "READERS",
    "DiscoveringModel",
    "Result",
    "answer",
    "blinded",
    "results",
    "solve",
]
