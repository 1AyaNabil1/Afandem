"""Solvability (docs/dataset-spec.md §2 lint table; docs/harness-spec.md §10).

Runs the discovering oracle (`afandem.providers.discover.solve`, the same episode as
tests/test_solvability.py): one offline episode on the scenario with `expected` removed, scored
against the real `expected`. An `act`, `ask` or `inform` item it cannot solve is an error: an id
the text does not lead to through the tools, an answer no tool returns, or a slot table the
oracle cannot read yet (then extend `providers/discover.py`). A gold that cannot be prepared (an
`end_state_patch` that does not apply, or expected calls whose replay disagrees with it) is an
error too. `none`, `refuse` and `out_of_scope` items are not run (the oracle only replies), and
an initial state that does not load is left to the `state` lint. An episode takes milliseconds
and makes no network call.
"""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError

from afandem.lints.findings import Finding
from afandem.sandbox import DOMAINS, new_state
from afandem.scenarios.schema import Scenario

RULE = "solvability"
SOLVED_BEHAVIOURS = frozenset({"act", "ask", "inform"})


def run_sync[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion, also when called from inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def _loads(scenario: Scenario) -> bool:
    try:
        new_state(
            scenario.domain,
            scenario.initial_state,
            user_identity=scenario.user_identity,
            now=scenario.now.aware,
        )
    except (ValidationError, ValueError):
        return False
    return True


def check_solvability(scenario: Scenario) -> list[Finding]:
    if scenario.behaviour not in SOLVED_BEHAVIOURS or scenario.domain not in DOMAINS:
        return []
    if not _loads(scenario):
        return []  # the state lint reports it
    # The oracle and the scorer import afandem.lints (folding, lexicons), so importing them at
    # the top of this module would make the package import itself.
    from afandem.providers.discover import solve  # noqa: PLC0415
    from afandem.scoring.end_state import PatchError  # noqa: PLC0415

    try:
        episode, scores = run_sync(solve(scenario))
    except PatchError as exc:
        message = f"the expected end state cannot be prepared: {exc}"
        return [Finding(RULE, message, field="expected")]
    except Exception as exc:  # an oracle or sandbox bug must not abort the whole lint run
        return [Finding(RULE, f"the discovering oracle failed: {type(exc).__name__}: {exc}")]
    if scores.task_success:
        return []
    reasons = "; ".join(scores.reasons) or episode.outcome
    made = ", ".join(call.name for call in episode.tool_calls) or "none"
    message = (
        "the discovering oracle (slot table and tool results, never `expected`) did not solve "
        f"it: {reasons} (calls: {made}). Either the text does not lead to an id or an answer "
        "through the tools, or the oracle cannot read this slot table yet "
        "(src/afandem/providers/discover.py)"
    )
    return [Finding(RULE, message)]
