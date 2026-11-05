from pathlib import Path

import pytest
from pydantic import BaseModel

import afandem.sandbox
from afandem.sandbox import (
    BANKING_TOOLS,
    CLINIC_TOOLS,
    DOMAINS,
    BankingState,
    ClinicState,
    new_state,
    registry_for,
    state_collisions,
)

SANDBOX_DIR = Path(afandem.sandbox.__file__).parent
FORBIDDEN = ("random", "uuid", "datetime.now", "time.time", ".today(", "secrets")

CLINIC_MINIMAL = {
    "calendar": {"closed": ["Fri"], "hours": [{"open": "10:00", "close": "22:00"}]},
    "patients": [{"id": "p_17", "name": "منى محمود عبد الحليم", "phone": "+201000000017"}],
    "doctors": [{"id": "d_2", "name": "د. هبة السيد", "gender": "f", "specialty": "dermatology"}],
}


def test_sandbox_has_no_source_of_nondeterminism() -> None:
    sources = sorted(SANDBOX_DIR.glob("*.py"))
    assert len(sources) >= 8
    offenders = [
        (path.name, word) for path in sources for word in FORBIDDEN if word in path.read_text()
    ]
    assert offenders == []


def test_domain_registry() -> None:
    assert {
        "clinic": (ClinicState, CLINIC_TOOLS),
        "banking": (BankingState, BANKING_TOOLS),
    } == DOMAINS
    for state_type, tools in DOMAINS.values():
        assert registry_for(state_type) is tools
        assert tools.state_type is state_type
    assert len(CLINIC_TOOLS) == 7 and len(BANKING_TOOLS) == 5
    assert "telecom" not in DOMAINS


def test_new_state_injects_the_principal_and_builds_fresh_states() -> None:
    first = new_state("clinic", CLINIC_MINIMAL, user_identity={"patient_id": "p_17"})
    second = new_state("clinic", CLINIC_MINIMAL, user_identity={"patient_id": "p_17"})
    assert isinstance(first, ClinicState) and isinstance(second, ClinicState)
    assert first.user_identity.patient_id == "p_17"
    first.patients[0].aliases.append("Mona Mahmoud")
    assert second.patients[0].aliases == []
    assert "user_identity" not in CLINIC_MINIMAL
    with pytest.raises(KeyError):
        new_state("telecom", {}, user_identity={})


def test_state_collisions_needs_a_domain_state() -> None:
    class Other(BaseModel):
        pass

    with pytest.raises(TypeError):
        state_collisions(Other())
