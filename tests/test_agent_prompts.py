"""The prompt renderer: variables, placeholders, versions, the stub and the refusal."""

from pathlib import Path

import pytest

from afandem.agent.prompts import (
    PROMPTS_ENV,
    STUB_VERSION,
    PromptNotAuthoredError,
    PromptSet,
    PromptTemplateError,
    placeholders,
    prompt_variables,
    prompts_dir,
)
from afandem.scenarios import load_scenario, load_scenarios

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = load_scenario(FIXTURES / "scenarios" / "clinic" / "clinic-0042.json").scenario
SMOKE = {item.scenario.id: item.scenario for item in load_scenarios(FIXTURES / "smoke")}

# Test templates: placeholders only, no prompt wording.
SYSTEM = "S|{date_iso}|{time_hm}|{weekday}\n{policy}\n{{literal}}"
CLINIC = "C|{identity_patient_id}|{closed_days}|{opening_hours}"
BANKING = "B|{daily_limit_egp}|{identity_customer_id}"


def write(directory: Path, **files: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (directory / f"{name}.txt").write_text(text, encoding="utf-8")
    return directory


def test_variables_are_machine_formats() -> None:
    variables = prompt_variables(EXAMPLE)
    assert variables["date_iso"] == "2026-11-04"
    assert variables["date_dmy"] == "04/11/2026"
    assert variables["time_hm"] == "10:00"
    assert variables["weekday"] == "Wednesday"
    assert variables["utc_offset"] == "+02:00"
    assert variables["tz"] == "Africa/Cairo"
    assert variables["datetime_iso"] == "2026-11-04T10:00:00+02:00"
    assert variables["domain"] == "clinic"
    assert variables["identity_patient_id"] == "p_17"
    assert variables["identity_phone"] == "+201000000017"
    assert variables["user_identity_json"] == '{"patient_id":"p_17","phone":"+201000000017"}'
    assert variables["closed_days"] == "Fri"
    assert variables["opening_hours"] == "10:00-22:00"
    assert variables["holidays"].startswith("2026-01-07,2026-01-25")
    assert variables["calendar_json"].startswith('{"closed":["Fri"]')
    assert "daily_limit_egp" not in variables


def test_banking_variables_and_a_summer_offset() -> None:
    variables = prompt_variables(SMOKE["banking-9001"])
    assert variables["daily_limit_egp"] == "50000"
    assert variables["identity_customer_id"] == "c_9001"
    assert "calendar_json" not in variables
    data = SMOKE["banking-9001"].model_dump(mode="json", by_alias=True)
    data["now"] = {"local": "2026-07-01T09:30:00", "tz": "Africa/Cairo", "weekday": "Wednesday"}
    summer = type(SMOKE["banking-9001"]).model_validate(data)
    assert prompt_variables(summer)["utc_offset"] == "+03:00"


def test_render_inserts_the_policy(tmp_path: Path) -> None:
    prompts = PromptSet.load(write(tmp_path, system=SYSTEM, policy_clinic=CLINIC))
    assert prompts.render(EXAMPLE) == (
        "S|2026-11-04|10:00|Wednesday\nC|p_17|Fri|10:00-22:00\n{literal}"
    )
    assert not prompts.is_stub and prompts.source == tmp_path


def test_version_hashes_every_template(tmp_path: Path) -> None:
    first = PromptSet.load(write(tmp_path, system=SYSTEM, policy_clinic=CLINIC)).version
    assert len(first) == 12 and int(first, 16) >= 0
    assert PromptSet.load(tmp_path).version == first
    write(tmp_path, policy_banking=BANKING)
    second = PromptSet.load(tmp_path).version
    assert second != first
    write(tmp_path, policy_banking=BANKING + " ")
    assert PromptSet.load(tmp_path).version != second


def test_missing_system_prompt_refuses_a_real_run(tmp_path: Path) -> None:
    with pytest.raises(PromptNotAuthoredError, match=r"system\.txt.*owner's text.*prompts\.md"):
        PromptSet.load(tmp_path)


def test_missing_system_prompt_gives_the_fake_the_stub(tmp_path: Path) -> None:
    prompts = PromptSet.load(tmp_path, allow_stub=True)
    assert prompts.is_stub and prompts.version == STUB_VERSION
    rendered = prompts.render(EXAMPLE)
    assert rendered.startswith("[OFFLINE TEST STUB")
    assert "2026-11-04T10:00:00+02:00" in rendered and '"closed":["Fri"]' in rendered
    assert "daily_limit_egp=50000" in prompts.render(SMOKE["banking-9002"])


def test_an_authored_prompt_is_used_by_the_fake_too(tmp_path: Path) -> None:
    prompts = PromptSet.load(write(tmp_path, system=SYSTEM, policy_clinic=CLINIC), allow_stub=True)
    assert not prompts.is_stub


def test_missing_policy_is_not_authored(tmp_path: Path) -> None:
    prompts = PromptSet.load(write(tmp_path, system=SYSTEM, policy_clinic=CLINIC))
    with pytest.raises(PromptNotAuthoredError, match=r"policy_banking\.txt"):
        prompts.render(SMOKE["banking-9001"])


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ("{patient_name}", r"unknown placeholder \{patient_name\}"),
        ("{daily_limit_egp}", r"unknown placeholder \{daily_limit_egp\}"),  # banking-only
        ("{date_iso.year}", "attribute or index access"),
        ("{user_identity_json[0]}", "attribute or index access"),
        ("{}", "positional placeholder"),
        ("{0}", "positional placeholder"),
    ],
)
def test_unknown_placeholders_are_named(tmp_path: Path, policy: str, message: str) -> None:
    prompts = PromptSet.load(write(tmp_path, system=SYSTEM, policy_clinic=policy))
    with pytest.raises(PromptTemplateError, match=message):
        prompts.render(EXAMPLE)


def test_system_prompt_needs_the_policy_placeholder(tmp_path: Path) -> None:
    with pytest.raises(PromptTemplateError, match=r"\{policy\}"):
        PromptSet.load(write(tmp_path, system="S|{date_iso}"))


def test_placeholders() -> None:
    assert placeholders("a {x} {{y}} {z!r:>4}") == ["x", "z"]


def test_prompts_dir_honours_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PROMPTS_ENV, str(tmp_path))
    assert prompts_dir() == tmp_path
    write(tmp_path, system=SYSTEM, policy_clinic=CLINIC)
    assert PromptSet.load().source == tmp_path
    monkeypatch.delenv(PROMPTS_ENV)
    assert prompts_dir().parts[-2:] == ("config", "prompts")
