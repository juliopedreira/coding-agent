import subprocess
from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.shell import run_shell


def test_shell_runs_command(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    result = run_shell(boundary, "echo hello", workdir=tmp_path)

    assert result["returncode"] == 0
    assert result["stdout"].strip() == "hello"
    assert result["stderr"] == ""


def test_shell_timeout(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        run_shell(boundary, "sleep 1", timeout_ms=10)


def test_shell_truncation(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    text = "x" * 20_000
    result = run_shell(boundary, f"python - <<'PY'\nprint('{text}')\nPY", max_bytes=1000, max_lines=5)

    assert result["stdout_truncated"] is True
    assert result["stdout"].endswith("[truncated]")


def test_shell_non_zero_exit(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    result = run_shell(boundary, "bash -c 'echo err 1>&2; exit 7'")

    assert result["returncode"] == 7
    assert "err" in result["stderr"]
