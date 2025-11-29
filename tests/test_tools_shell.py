import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lincona.tools.shell import ShellInput, ShellOutput, ShellTool, run_shell, tool_registrations


def test_shell_runs_command(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    called: dict[str, str] = {}

    def fake_run(command, **kwargs):
        called.update(command=command, cwd=kwargs.get("cwd", ""))
        return SimpleNamespace(stdout="hello\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_shell(restricted_boundary, "echo hello", workdir=".")

    assert result["stdout"] == "hello\n"
    assert called["cwd"] == str(restricted_boundary.sanitize_workdir("."))


def test_shell_timeout(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    def fake_run(*_, **__):
        raise subprocess.TimeoutExpired(cmd="sleep", timeout=0.001)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_shell(restricted_boundary, "sleep 1", timeout_ms=10)

    assert result["timeout"] is True
    assert result["returncode"] is None


def test_shell_truncation(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    text = "x" * 20_000

    def fake_run(*_, **__):
        return SimpleNamespace(stdout=text, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_shell(restricted_boundary, "ignored", max_bytes=1000, max_lines=5)

    assert result["stdout_truncated"] is True
    assert result["stdout"].endswith("[truncated]")


def test_shell_non_zero_exit(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    def fake_run(*_, **__):
        return SimpleNamespace(stdout="", stderr="err", returncode=7)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_shell(restricted_boundary, "bash -c 'echo err 1>&2; exit 7'")

    assert result["returncode"] == 7
    assert "err" in result["stderr"]


def test_shell_rejects_empty_command(restricted_boundary):
    with pytest.raises(ValueError):
        run_shell(restricted_boundary, "   ")


def test_shell_input_casts_path_workdir():
    validated = ShellInput.model_validate({"command": "echo", "workdir": Path("/tmp/path")})
    assert isinstance(validated.workdir, str)


def test_shell_tool_execute_and_end_event(monkeypatch: pytest.MonkeyPatch, restricted_boundary):
    monkeypatch.setattr(
        "lincona.tools.shell.run_shell",
        lambda boundary, **kwargs: {
            "stdout": "ok",
            "stderr": "",
            "returncode": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout": False,
            "message": None,
        },
    )
    tool = ShellTool(restricted_boundary)
    output = tool.execute(ShellInput(command="echo", workdir=None, timeout_ms=1))
    assert isinstance(output, ShellOutput)
    reg = tool_registrations(restricted_boundary)[0]
    end_data = reg.end_event_builder(ShellInput(command="echo"), output)  # type: ignore[arg-type]
    assert end_data == {"returncode": 0, "timeout": False}
