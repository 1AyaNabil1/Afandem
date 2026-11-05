"""The agent loop (rounds, follow-up rule v1, deadline) and the system-prompt renderer."""

from afandem.agent.loop import (
    DEADLINE_MS,
    FOLLOW_UP_RULE,
    MAX_ROUNDS,
    CallRow,
    CompletionRow,
    Episode,
    TurnRecord,
    follow_up_due,
    run_episode,
)
from afandem.agent.prompts import (
    PromptNotAuthoredError,
    PromptSet,
    PromptTemplateError,
    prompt_variables,
)

__all__ = [
    "DEADLINE_MS",
    "FOLLOW_UP_RULE",
    "MAX_ROUNDS",
    "CallRow",
    "CompletionRow",
    "Episode",
    "PromptNotAuthoredError",
    "PromptSet",
    "PromptTemplateError",
    "TurnRecord",
    "follow_up_due",
    "prompt_variables",
    "run_episode",
]
