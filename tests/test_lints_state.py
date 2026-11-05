from pathlib import Path

from afandem.lints.state import check_state
from afandem.scenarios import load_scenario

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"


def test_fixture_state_loads_into_the_clinic_sandbox() -> None:
    assert check_state(load_scenario(FIXTURE).scenario) == []
