from pathlib import Path

import pytest

from web_api.app import AGENT1_BACKEND_ROOT, ROOT, _pipeline_command


REF_NO = "reference_no_0000001"


def _value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def test_default_backend_uses_new_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PIPELINE_BACKEND", raising=False)

    command = _pipeline_command(tmp_path, REF_NO)

    assert command[1] == str(AGENT1_BACKEND_ROOT / "pipeline_runner.py")
    assert command[2:4] == ["--workflow", "legacy"]
    assert _value(command, "--config") == str(
        AGENT1_BACKEND_ROOT / "extraction" / "config" / "pipeline.yaml"
    )
    assert _value(command, "--env-file") == str(AGENT1_BACKEND_ROOT / "ocr" / ".env")
    assert command[-1] == "--preview"


def test_explicit_legacy_backend_keeps_old_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PIPELINE_BACKEND", "legacy")

    command = _pipeline_command(tmp_path, REF_NO)

    assert command[1] == str(ROOT / "pipeline_runner.py")
    assert "--workflow" not in command
    assert _value(command, "--config") == str(ROOT / "extraction" / "config" / "pipeline.yaml")
    assert _value(command, "--env-file") == str(ROOT / ".env")


def test_agent1_legacy_backend_switches_script_config_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PIPELINE_BACKEND", "agent1_legacy")

    command = _pipeline_command(tmp_path, REF_NO)

    assert command[1] == str(AGENT1_BACKEND_ROOT / "pipeline_runner.py")
    assert command[2:4] == ["--workflow", "legacy"]
    assert _value(command, "--config") == str(
        AGENT1_BACKEND_ROOT / "extraction" / "config" / "pipeline.yaml"
    )
    assert _value(command, "--env-file") == str(AGENT1_BACKEND_ROOT / "ocr" / ".env")
    assert _value(command, "--output-dir") == str(tmp_path / "output")
    assert _value(command, "--input-dir") == str(tmp_path / "source_pdfs")


def test_backend_python_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python = tmp_path / "python-backend"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("PIPELINE_BACKEND", "agent1_legacy")
    monkeypatch.setenv("PIPELINE_BACKEND_PYTHON", str(python))

    command = _pipeline_command(tmp_path, REF_NO)

    assert command[0] == str(python)


def test_unknown_backend_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PIPELINE_BACKEND", "agent1")

    with pytest.raises(ValueError, match="PIPELINE_BACKEND"):
        _pipeline_command(tmp_path, REF_NO)
