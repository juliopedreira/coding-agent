"""Shell command execution with boundary enforcement and output caps."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.limits import truncate_output
from lincona.tools.registry import ToolRegistration


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


class ShellInput(ToolRequest):
    command: str = Field(description="Shell command to run.")
    workdir: str | Path | None = Field(default=None, description="Working directory (optional).")
    timeout_ms: int = Field(default=60000, ge=1, description="Timeout in milliseconds.")


class ShellOutput(ToolResponse):
    stdout: str
    stderr: str
    returncode: int | None
    stdout_truncated: bool
    stderr_truncated: bool
    timeout: bool
    message: str | None = None


class ShellTool(Tool[ShellInput, ShellOutput]):
    name = "shell"
    description = "Run a shell command"
    InputModel = ShellInput
    OutputModel = ShellOutput
    requires_approval = True

    def __init__(self, boundary: FsBoundary) -> None:
        self.boundary = boundary

    def execute(self, request: ShellInput) -> ShellOutput:
        result = run_shell(self.boundary, **request.model_dump())
        return ShellOutput.model_validate(result)


def tool_registrations(boundary: FsBoundary) -> list[ToolRegistration]:
    tool = ShellTool(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        out = cast(ShellOutput, output)
        return {"returncode": out.returncode, "timeout": out.timeout}

    return [
        ToolRegistration(
            name="shell",
            description="Run a shell command",
            input_model=ShellInput,
            output_model=ShellOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], tool.execute),
            requires_approval=True,
            end_event_builder=_end_event,
        )
    ]


__all__ = ["run_shell", "tool_registrations", "ShellInput", "ShellOutput"]


__all__ = ["run_shell"]
