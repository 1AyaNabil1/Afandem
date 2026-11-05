"""Deterministic tool sandboxes: pydantic state per domain, typed tools, call-level recording.

Pilot domains: clinic and banking (telecom follows in v0 Phase 2).

    state = new_state("clinic", scenario["initial_state"], user_identity=scenario["user_identity"])
    record = execute(state, "book_appointment", '{"patient_id": "p_17", ...}')
    record.call_valid, record.attempted_write, record.mutated, record.content

Each episode starts from its own state (`new_state` builds a fresh model; `model_copy(deep=True)`
copies one), and `canonical(state)` is the form compared at the end.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from afandem.sandbox.banking import BANKING_TOOLS, BankingState
from afandem.sandbox.clinic import CLINIC_TOOLS, ClinicState
from afandem.sandbox.clock import as_date, parse_now
from afandem.sandbox.names import Collision
from afandem.sandbox.tools import (
    CallRecord,
    ToolRegistry,
    ToolSpec,
    canonical,
    canonical_json,
    execute,
    registry_for,
)

DOMAINS: dict[str, tuple[type[BaseModel], ToolRegistry[Any]]] = {
    "clinic": (ClinicState, CLINIC_TOOLS),
    "banking": (BankingState, BANKING_TOOLS),
}


def new_state(
    domain: str,
    initial_state: Mapping[str, Any],
    *,
    user_identity: Mapping[str, Any],
    now: Mapping[str, object] | date | datetime | str | None = None,
) -> BaseModel:
    """Validate a scenario's `initial_state` into a fresh domain state.

    `user_identity` (the authenticated principal) is injected; banking also needs `now` (a
    scenario `now` block, a date or a datetime), whose Cairo date becomes `today`.
    """
    state_type, _ = DOMAINS[domain]
    data = dict(initial_state)
    data["user_identity"] = dict(user_identity)
    if domain == "banking" and "today" not in data:
        if now is None:
            raise ValueError("banking state needs `now` (or `today` in the initial state)")
        moment = parse_now(now) if isinstance(now, Mapping) else now
        data["today"] = as_date(moment).isoformat()
    return state_type.model_validate(data)


def state_collisions(state: BaseModel) -> list[Collision]:
    """The state-collision lint: identity records the lookup cannot tell apart.

    A scenario tagged `name_ambiguous` expects some; any other scenario expects none.
    """
    if isinstance(state, ClinicState | BankingState):
        return state.identity_collisions()
    raise TypeError(f"no identity records in {type(state).__name__}")


__all__ = [
    "BANKING_TOOLS",
    "CLINIC_TOOLS",
    "DOMAINS",
    "BankingState",
    "CallRecord",
    "ClinicState",
    "Collision",
    "ToolRegistry",
    "ToolSpec",
    "canonical",
    "canonical_json",
    "execute",
    "new_state",
    "registry_for",
    "state_collisions",
]
