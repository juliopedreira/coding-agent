"""Shell command execution with boundary enforcement and output caps."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lincona.tools.fs import FsBoundary
from lincona.tools.limits import truncate_output


def run_shell(
    boundary: FsBoundary,
    command: str,
    *,
    workdir: str | Path | None = None,
    timeout_ms: int = 60_000,
    max_bytes: int = 8_192,
    max_lines: int = 200,
) -> dict[str, object]:
    """Execute a shell command with truncation and return structured result."""

    if not command.strip():
        raise ValueError("command cannot be empty")

    cwd = boundary.sanitize_workdir(workdir)

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000,
        )
        stdout, stdout_trunc = truncate_output(completed.stdout, max_bytes=max_bytes, max_lines=max_lines)
        stderr, stderr_trunc = truncate_output(completed.stderr, max_bytes=max_bytes, max_lines=max_lines)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": completed.returncode,
            "stdout_truncated": stdout_trunc,
            "stderr_truncated": stderr_trunc,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout": True,
            "message": str(exc),
        }


__all__ = ["run_shell"]
