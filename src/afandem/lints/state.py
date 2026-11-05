"""The scenario's initial state must load into its domain sandbox, and identity records must
not collide unless the scenario is about an ambiguous name."""

from pydantic import ValidationError

from afandem.lints.findings import Finding
from afandem.sandbox import DOMAINS, new_state, state_collisions
from afandem.scenarios.schema import Scenario

AMBIGUITY_TAG = "name_ambiguous"


def check_state(scenario: Scenario) -> list[Finding]:
    if scenario.domain not in DOMAINS:
        message = f"no sandbox for domain {scenario.domain!r} yet"
        return [Finding("state", message, field="initial_state", severity="warning")]
    try:
        state = new_state(
            scenario.domain,
            scenario.initial_state,
            user_identity=scenario.user_identity,
            now=scenario.now.aware,
        )
    except (ValidationError, ValueError) as exc:
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return [Finding("state", f"initial_state does not load: {detail}", field="initial_state")]
    collisions = state_collisions(state)
    ambiguous = AMBIGUITY_TAG in scenario.phenomena
    if collisions and not ambiguous:
        listed = "; ".join(f"{c.kind} {c.key!r}: {', '.join(c.ids)}" for c in collisions)
        return [Finding("state", f"identity records collide: {listed}", field="initial_state")]
    if ambiguous and not collisions:
        message = f"tagged {AMBIGUITY_TAG} but no two records collide"
        return [Finding("state", message, field="initial_state")]
    return []
