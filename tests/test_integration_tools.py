"""The scenario schema's tool table must match the tools the sandboxes implement."""

import pytest

from afandem.sandbox import DOMAINS
from afandem.scenarios import DOMAIN_TOOLS


@pytest.mark.parametrize("domain", sorted(DOMAINS))
def test_schema_tool_table_matches_sandbox(domain: str) -> None:
    _, registry = DOMAINS[domain]
    implemented = {name: name in registry.mutating() for name in registry.names()}
    assert dict(DOMAIN_TOOLS[domain]) == implemented  # type: ignore[index]
