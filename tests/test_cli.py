import pytest

from afandem import __version__
from afandem.cli import KEY_VARIABLES, main


def test_version_is_set() -> None:
    assert __version__ == "0.0.1"


def test_fake_run_needs_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    assert main(["run", "--fake"]) == 0


def test_real_run_without_keys_exits_before_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    assert main(["run"]) == 2
    assert "no provider key found" in capsys.readouterr().err
