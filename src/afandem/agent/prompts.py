"""The system prompt: the owner's templates, rendered per scenario from machine-format facts.

The wording is Aya's. This module only loads `config/prompts/system.txt` and
`config/prompts/policy_<domain>.txt`, fills their placeholders with `str.format_map` and hashes
them; it never supplies prompt text of its own except the offline-test stub, which is visibly
marked and used only by `afandem run --fake` when `system.txt` has not been written yet.

Rendering: the policy file of the scenario's domain is rendered first and inserted at `{policy}`
in `system.txt` (which must contain it). Variables are strings, all in machine formats
(docs/prompts.md lists them with examples):

- clock: `date_iso`, `date_dmy`, `time_hm`, `weekday`, `utc_offset`, `tz`, `datetime_iso`;
- identity: `identity_<key>` for each `user_identity` key, `user_identity_json`;
- `domain`;
- clinic (from the state): `calendar_json`, `closed_days`, `opening_hours`, `holidays`;
- banking (from the state): `daily_limit_egp`.

A placeholder outside that set, or one using attribute or index access, is an error naming it.
Literal braces in a template are written `{{` and `}}`.

`prompt_version` is the first 12 hex digits of SHA-256 over the renderer version and every
template file (name and bytes, sorted by name); the stub's version is `"stub"`.
"""

import hashlib
import os
import string
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from afandem.providers.base import canonical_json
from afandem.sandbox import new_state
from afandem.sandbox.banking import BankingState, piastres_to_egp
from afandem.sandbox.clinic import ClinicState
from afandem.sandbox.clock import offset_str
from afandem.scenarios import Scenario

RENDERER_VERSION: Final = "1"
SYSTEM_FILE: Final = "system.txt"
POLICY_PREFIX: Final = "policy_"
PROMPTS_ENV: Final = "AFANDEM_PROMPTS_DIR"
DEFAULT_PROMPTS_DIR: Final = Path(__file__).resolve().parents[3] / "config" / "prompts"
STUB_VERSION: Final = "stub"

# The offline-test stub: placeholders only, no prompt wording. Never used by a real run.
STUB_SYSTEM: Final = (
    "[OFFLINE TEST STUB - not the benchmark prompt] domain={domain} now={datetime_iso} "
    "weekday={weekday} user={user_identity_json}\n{policy}"
)
STUB_POLICIES: Final[Mapping[str, str]] = {
    "clinic": "[stub policy clinic] calendar={calendar_json}",
    "banking": "[stub policy banking] daily_limit_egp={daily_limit_egp}",
}


class PromptNotAuthoredError(Exception):
    """A template the owner has not written yet; real runs refuse to start without it."""


class PromptTemplateError(ValueError):
    """A template uses a placeholder outside the documented variable set."""


def policy_file(domain: str) -> str:
    return f"{POLICY_PREFIX}{domain}.txt"


def prompts_dir() -> Path:
    """`$AFANDEM_PROMPTS_DIR` when set, else `config/prompts/` in the repository."""
    configured = os.environ.get(PROMPTS_ENV)
    return Path(configured) if configured else DEFAULT_PROMPTS_DIR


def prompt_variables(scenario: Scenario) -> dict[str, str]:
    """The documented variable set for one scenario, every value in a machine format."""
    now = scenario.now.aware
    identity = scenario.user_identity
    variables: dict[str, str] = {
        "domain": scenario.domain,
        "date_iso": now.date().isoformat(),
        "date_dmy": now.strftime("%d/%m/%Y"),
        "time_hm": now.strftime("%H:%M"),
        "weekday": scenario.now.weekday,
        "utc_offset": offset_str(now),
        "tz": scenario.now.tz,
        "datetime_iso": now.isoformat(timespec="seconds"),
        "user_identity_json": canonical_json(dict(identity)),
    }
    for key, value in identity.items():
        variables[f"identity_{key}"] = value
    state = new_state(
        scenario.domain, scenario.initial_state, user_identity=identity, now=scenario.now.aware
    )
    if isinstance(state, ClinicState):
        calendar = state.calendar
        variables["calendar_json"] = canonical_json(calendar.model_dump(mode="json"))
        variables["closed_days"] = ",".join(calendar.closed)
        variables["opening_hours"] = ",".join(f"{h.open}-{h.close}" for h in calendar.hours)
        variables["holidays"] = ",".join(sorted(calendar.holidays))
    elif isinstance(state, BankingState):
        variables["daily_limit_egp"] = str(piastres_to_egp(state.daily_limit_piastres))
    return variables


def placeholders(template: str) -> list[str]:
    """The field names a format template uses, in order (`{{`/`}}` are literal braces)."""
    return [
        field
        for _, field, _, _ in string.Formatter().parse(template)
        if field is not None  # None: trailing literal text
    ]


def render_template(template: str, variables: Mapping[str, str], *, source: str) -> str:
    known = set(variables)
    for field in placeholders(template):
        if field == "" or field.isdigit():
            raise PromptTemplateError(f"{source}: positional placeholder {{{field}}} not allowed")
        if field not in known:
            if "." in field or "[" in field:
                raise PromptTemplateError(
                    f"{source}: placeholder {{{field}}} uses attribute or index access"
                )
            raise PromptTemplateError(
                f"{source}: unknown placeholder {{{field}}} (known: {', '.join(sorted(known))})"
            )
    return template.format_map(variables)


def _version(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(f"renderer:{RENDERER_VERSION}\0".encode())
    for name in sorted(files):
        digest.update(name.encode("utf-8") + b"\0" + files[name] + b"\0")
    return digest.hexdigest()[:12]


@dataclass(frozen=True)
class PromptSet:
    """The templates of one run: the system prompt and one policy block per domain."""

    system: str
    policies: Mapping[str, str]
    version: str
    source: Path | None
    """The directory read, or None for the built-in offline-test stub."""

    @property
    def is_stub(self) -> bool:
        return self.source is None

    @classmethod
    def stub(cls) -> "PromptSet":
        return cls(system=STUB_SYSTEM, policies=STUB_POLICIES, version=STUB_VERSION, source=None)

    @classmethod
    def load(cls, directory: Path | None = None, *, allow_stub: bool = False) -> "PromptSet":
        """Read the templates; without `system.txt` return the stub (`allow_stub`, i.e.
        `--fake`) or raise `PromptNotAuthoredError`."""
        directory = prompts_dir() if directory is None else directory
        system_path = directory / SYSTEM_FILE
        if not system_path.is_file():
            if allow_stub:
                return cls.stub()
            raise PromptNotAuthoredError(
                f"{system_path} does not exist. The system prompt is the owner's text: "
                f"write {SYSTEM_FILE} (with a {{policy}} placeholder) and one "
                f"{POLICY_PREFIX}<domain>.txt per domain there (see docs/prompts.md) before a "
                "real run."
            )
        files = {SYSTEM_FILE: system_path.read_bytes()}
        for path in sorted(directory.glob(f"{POLICY_PREFIX}*.txt")):
            files[path.name] = path.read_bytes()
        system = files[SYSTEM_FILE].decode("utf-8")
        if "policy" not in placeholders(system):
            raise PromptTemplateError(f"{system_path}: the {{policy}} placeholder is missing")
        policies = {
            name.removeprefix(POLICY_PREFIX).removesuffix(".txt"): data.decode("utf-8")
            for name, data in files.items()
            if name != SYSTEM_FILE
        }
        return cls(system=system, policies=policies, version=_version(files), source=directory)

    def render(self, scenario: Scenario) -> str:
        """The system prompt for one scenario."""
        policy = self.policies.get(scenario.domain)
        if policy is None:
            where = "the stub" if self.source is None else str(self.source)
            raise PromptNotAuthoredError(
                f"no {policy_file(scenario.domain)} in {where}: the {scenario.domain} policy "
                "block is the owner's text (see docs/prompts.md)"
            )
        variables = prompt_variables(scenario)
        rendered_policy = render_template(policy, variables, source=policy_file(scenario.domain))
        return render_template(
            self.system, {**variables, "policy": rendered_policy}, source=SYSTEM_FILE
        )


__all__ = [
    "DEFAULT_PROMPTS_DIR",
    "PROMPTS_ENV",
    "RENDERER_VERSION",
    "STUB_VERSION",
    "PromptNotAuthoredError",
    "PromptSet",
    "PromptTemplateError",
    "placeholders",
    "policy_file",
    "prompt_variables",
    "prompts_dir",
    "render_template",
]
