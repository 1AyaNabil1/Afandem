"""The smoke fixtures: schema-valid, placeholder-only texts, synthetic ids, the project canary."""

import re
from pathlib import Path

from afandem.canary import CANARY_STRING
from afandem.sandbox import new_state
from afandem.sandbox.names import has_arabic
from afandem.scenarios import load_scenarios
from afandem.scoring import expected_state

SMOKE = Path(__file__).parent / "fixtures" / "smoke"
LOADED = load_scenarios(SMOKE)
PLACEHOLDER = re.compile(r"\[fixture (?P<id>[a-z]+-[0-9]{4}) (?P<column>[a-z_]+) [a-z -]+\]")


def test_fixtures_load_against_the_schema() -> None:
    assert len(LOADED) >= 8
    for item in LOADED:
        scenario = item.scenario
        assert int(scenario.id.split("-")[1]) >= 9001
        assert scenario.canary == CANARY_STRING
        new_state(
            scenario.domain,
            scenario.initial_state,
            user_identity=scenario.user_identity,
            now=scenario.now.aware,
        )
        expected_state(scenario)


def test_every_text_is_a_neutral_placeholder() -> None:
    for item in LOADED:
        for column, block in item.scenario.texts.columns():
            for _, text in block.fields_with_text():
                match = PLACEHOLDER.fullmatch(text)
                assert match is not None, (item.scenario.id, column, text)
                assert match["id"] == item.scenario.id and match["column"] == column


def test_state_names_are_latin_placeholders() -> None:
    for item in LOADED:
        state = item.scenario.initial_state
        for collection in ("patients", "doctors", "beneficiaries"):
            for record in state.get(collection, []):
                assert "Placeholder" in record["name"]
                assert not has_arabic(record["name"])
                assert all(not has_arabic(alias) for alias in record.get("aliases", []))
