import json
from pathlib import Path
from typing import Any

import pytest

from afandem import __version__, cli
from afandem.agent.prompts import PROMPTS_ENV
from afandem.cli import KEY_VARIABLES, main
from afandem.providers.base import (
    AssistantMsg,
    BudgetedProvider,
    Completion,
    Provider,
    Request,
    Target,
)
from afandem.providers.cache import ResponseCache
from afandem.trace import INDEX_FILE, RUN_FILE, TRACES_FILE, read_index, read_traces

SMOKE = str(Path(__file__).parent / "fixtures" / "smoke")
ITEMS = 9 * 6


@pytest.fixture(autouse=True)
def _no_keys_and_no_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(PROMPTS_ENV, str(tmp_path / "no-prompts"))


def fake_run(runs: Path, *extra: str) -> int:
    return main(["run", "--fake", "--scenarios", SMOKE, "--runs-dir", str(runs), *extra])


def test_version_is_set() -> None:
    assert __version__ == "0.0.1"


def test_fake_run_needs_no_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fake_run(tmp_path, "--run-id", "r") == 0
    out = capsys.readouterr().out
    assert f"{ITEMS} item(s) written" in out
    assert len(read_index(tmp_path / "r")) == ITEMS
    for name in (TRACES_FILE, INDEX_FILE, RUN_FILE, "tools.json"):
        assert (tmp_path / "r" / name).exists()


def test_real_run_without_keys_exits_before_network(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run"]) == 2
    assert "no provider key found" in capsys.readouterr().err
    assert main(["run", "--target", "anything"]) == 2


def test_unknown_route_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(KEY_VARIABLES[0], "x")
    args = ["run", "--target", "qwen@groq", "--scenarios", SMOKE, "--cache", str(tmp_path / "c")]
    assert main(args) == 2
    assert "unknown route" in capsys.readouterr().err


def test_route_key_missing_exits_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_FREE_API_KEY", "x")  # some key, but not Groq's
    args = ["run", "--target", "groq_qwen", "--scenarios", SMOKE, "--cache", str(tmp_path / "c")]
    assert main(args) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


class _Replier:
    """Answers every request with a short text reply (no tool calls)."""

    async def complete(self, request: Request) -> Completion:
        del request
        return Completion(assistant=AssistantMsg(content="[test reply]"), finish_reason="stop")


def _write_test_prompts(directory: Path) -> None:
    directory.mkdir()
    (directory / "system.txt").write_text("[test system] {policy}", encoding="utf-8")
    for domain in ("clinic", "banking"):
        (directory / f"policy_{domain}.txt").write_text(f"[test {domain}]", encoding="utf-8")


@pytest.mark.parametrize(
    ("no_cache", "salts"),
    [(False, [None, "repeat-2"]), (True, ["nocache-r", "nocache-r|repeat-2"])],
)
def test_real_targets_are_wired_with_cache_and_per_repeat_salts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_cache: bool, salts: list[str | None]
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "x")
    prompts = tmp_path / "prompts"
    _write_test_prompts(prompts)
    monkeypatch.setenv(PROMPTS_ENV, str(prompts))
    seen: list[tuple[str, str | None, bool]] = []

    def fake_build(name: str, **kwargs: Any) -> tuple[Target, Provider]:
        seen.append((name, kwargs["salt"], kwargs["cache"] is not None))
        target = Target(name="t@test", route=name, model="m", params={})
        return target, BudgetedProvider(_Replier(), kwargs["budget"])

    monkeypatch.setattr(cli, "build_provider", fake_build)
    cache = tmp_path / "cache" / "responses.sqlite"
    args = ["run", "--target", "groq_qwen", "--scenarios", SMOKE, "--runs-dir", str(tmp_path)]
    args += ["--run-id", "r", "--repeat", "2", "--columns", "en", "--cache", str(cache)]
    assert main([*args, *(["--no-cache"] if no_cache else [])]) == 0
    assert [salt for _, salt, _ in seen] == salts
    assert all(has_cache for _, _, has_cache in seen)
    records = [record for _, record in read_traces(tmp_path / "r")]
    assert len(records) == 9 * 2
    assert {(r["repeat"], r["salt"]) for r in records} == {(1, salts[0]), (2, salts[1])}
    ResponseCache(cache).close()  # the CLI released the single-writer lock


def test_real_run_refuses_without_authored_prompts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "x")
    cache = tmp_path / "c.sqlite"
    args = ["run", "--target", "groq_qwen", "--scenarios", SMOKE, "--runs-dir", str(tmp_path)]
    assert main([*args, "--cache", str(cache)]) == 2
    assert "system.txt" in capsys.readouterr().err
    ResponseCache(cache).close()  # released on the error path too


def test_real_run_needs_a_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(KEY_VARIABLES[0], "x")
    assert main(["run", "--scenarios", SMOKE]) == 2
    assert "--target" in capsys.readouterr().err


def test_overrides_need_the_fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(KEY_VARIABLES[0], "x")
    args = ["run", "--target", "t", "--overrides", str(tmp_path / "o.json")]
    assert main(args) == 2
    assert "--fake" in capsys.readouterr().err


def test_dry_run_prints_the_plan_and_calls_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fake_run(tmp_path, "--dry-run", "--columns", "egy,en", "--repeat", "2") == 0
    out = capsys.readouterr().out
    assert "dry run: 36 item(s) = 9 scenario(s) x 2 column(s) x 1 target(s) x 2 repeat(s)" in out
    assert "prompt: stub (offline-test stub)" in out
    assert 'fake | fake | afandem/fake-oracle | {"max_tokens":4096,"tool_choice":"auto"}' in out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--columns", "egy,xx"], "unknown column"),
        (["--resume"], "--resume needs --run-id"),
        (["--retry-errors"], "--resume needs --run-id"),
        (["--repeat", "0"], ">= 1"),
        (["--budget", "-1"], ">= 0"),
    ],
)
def test_run_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    assert fake_run(tmp_path, *args) == 2
    assert message in capsys.readouterr().err


def test_missing_scenarios_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--fake", "--scenarios", str(tmp_path / "nope")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_bad_overrides_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "o.json"
    path.write_text('{"*": "no_such_mode"}', encoding="utf-8")
    assert fake_run(tmp_path / "runs", "--overrides", str(path)) == 2
    assert "--overrides" in capsys.readouterr().err


def test_inapplicable_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "o.json"
    path.write_text('{"*": "near_miss_date"}', encoding="utf-8")
    assert fake_run(tmp_path / "runs", "--overrides", str(path), "--run-id", "x") == 2
    assert "does not apply" in capsys.readouterr().err


def test_existing_run_dir_needs_resume(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fake_run(tmp_path, "--run-id", "r", "--columns", "en") == 0
    assert fake_run(tmp_path, "--run-id", "r", "--columns", "en") == 2
    assert "--resume" in capsys.readouterr().err
    assert fake_run(tmp_path, "--run-id", "r", "--resume") == 0


def test_budget_stop_exit_code_then_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fake_run(tmp_path, "--run-id", "b", "--budget", "10") == 3
    assert "stopped: budget" in capsys.readouterr().out
    meta = json.loads((tmp_path / "b" / RUN_FILE).read_text(encoding="utf-8"))
    assert meta["stopped"] == "budget" and meta["budget"] == 10
    assert fake_run(tmp_path, "--run-id", "b", "--resume") == 0
    assert len(read_index(tmp_path / "b")) == ITEMS


def test_quota_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "o.json"
    path.write_text('{"clinic-9001": "quota"}', encoding="utf-8")
    assert fake_run(tmp_path / "runs", "--run-id", "q", "--overrides", str(path)) == 4


def test_retry_errors_from_the_cli(tmp_path: Path) -> None:
    path = tmp_path / "o.json"
    path.write_text('{"banking-9003|cs": "error_200"}', encoding="utf-8")
    runs = tmp_path / "runs"
    assert fake_run(runs, "--run-id", "e", "--overrides", str(path)) == 0
    key = "banking-9003|cs|fake|1"
    assert read_index(runs / "e")[key]["outcome"] == "provider_error"
    assert fake_run(runs, "--run-id", "e", "--retry-errors") == 0
    assert read_index(runs / "e")[key]["outcome"] == "ok"


def test_show_prints_transcripts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fake_run(tmp_path, "--run-id", "s") == 0
    capsys.readouterr()
    assert main(["show", str(tmp_path / "s"), "--scenario", "clinic-9002", "--column", "egy"]) == 0
    out = capsys.readouterr().out
    assert "=== clinic-9002 | egy | fake | 1 ===" in out
    assert "behaviour: ask  outcome: ok  flags: -  follow-up: delivered (v1)" in out
    assert "score: task_success=True unsafe_read=False unsafe_write=False" in out
    assert "[user] [fixture clinic-9002 egy text]" in out
    assert "[user] [fixture clinic-9002 egy follow-up]" in out
    assert "[assistant] [fake] question" in out
    assert "-> book_appointment(" in out and "[valid, write, mutated]" in out
    assert '[tool book_appointment] {"appointment_id": "appt_0001"' in out
    assert out.count("===") == 2  # one item


def test_show_failure_reasons_and_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "o.json"
    path.write_text('{"clinic-9001|en": "length_mid_call"}', encoding="utf-8")
    assert fake_run(tmp_path / "runs", "--run-id", "f", "--overrides", str(path)) == 0
    capsys.readouterr()
    assert main(["show", str(tmp_path / "runs" / "f"), "--scenario", "clinic-9001"]) == 0
    out = capsys.readouterr().out
    assert "flags: length, truncated_tool_call" in out
    assert "reasons: length" in out
    assert "not executed" in out


def test_show_without_matches_and_missing_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fake_run(tmp_path, "--run-id", "s", "--columns", "en") == 0
    capsys.readouterr()
    assert main(["show", str(tmp_path / "s"), "--column", "egy"]) == 0
    assert "no matching items" in capsys.readouterr().out
    assert main(["show", str(tmp_path / "missing")]) == 2
    assert main(["summary", str(tmp_path / "missing")]) == 2


def test_summary_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "o.json"
    path.write_text(
        '{"clinic-9001|egy": "near_miss_date", "clinic-9005|egy": "http_403"}', encoding="utf-8"
    )
    assert fake_run(tmp_path / "runs", "--run-id", "t", "--overrides", str(path)) == 0
    capsys.readouterr()
    assert main(["summary", str(tmp_path / "runs" / "t")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("task success (successes/scored items), t")
    header = [cell.strip() for cell in lines[1].split("|")]
    assert header == ["target", "en", "msa", "egy", "arabizi", "cs", "cs_latin", "unscored"]
    row = [cell.strip() for cell in lines[2].split("|")]
    assert row == ["fake", "9/9", "9/9", "7/8", "9/9", "9/9", "9/9", "1"]


def test_data_lint_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    example = Path(__file__).parent / "fixtures" / "scenarios" / "clinic" / "clinic-0042.json"
    code = main(["data", "lint", str(example)])
    assert code in (0, 1)
    assert "1 file(s):" in capsys.readouterr().out


def test_cli_starts_without_the_routes_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(path: Path | None = None) -> list[str]:
        raise FileNotFoundError("config/routes.json")

    monkeypatch.setattr(cli, "route_names", missing)  # as in a wheel outside a checkout
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out
