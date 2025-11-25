"""Minimal PTY-backed exec manager."""

from __future__ import annotations

import os
import pty
import select
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field

from lincona.tools.base import Tool, ToolRequest, ToolResponse
from lincona.tools.fs import FsBoundary
from lincona.tools.limits import truncate_output
from lincona.tools.registry import ToolRegistration


@dataclass
class PtySession:
    pid: int
    fd: int
    cwd: Path


class PtyManager:
    def __init__(self, boundary: FsBoundary, *, max_bytes: int = 8_192, max_lines: int = 200) -> None:
        self.boundary = boundary
        self.sessions: dict[str, PtySession] = {}
        self.max_bytes = max_bytes
        self.max_lines = max_lines
        self._cumulative: dict[str, int] = {}

    def exec_command(self, session_id: str, cmd: str, workdir: str | Path | None = None) -> dict[str, object]:
        cwd = self.boundary.sanitize_workdir(workdir)
        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(cwd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        self.sessions[session_id] = PtySession(pid=proc.pid, fd=master_fd, cwd=cwd)
        self._cumulative[session_id] = 0
        return self._read(session_id)

    def write_stdin(self, session_id: str, chars: str) -> dict[str, object]:
        if session_id not in self.sessions:
            raise KeyError("session not found")
        os.write(self.sessions[session_id].fd, chars.encode())
        return self._read(session_id)

    def close(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            os.close(session.fd)
            self._cumulative.pop(session_id, None)

    def close_all(self) -> None:
        """Close all tracked PTY sessions."""

        for sid in list(self.sessions.keys()):
            self.close(sid)

    def _read(self, session_id: str) -> dict[str, object]:
        session = self.sessions[session_id]
        fd = session.fd
        out = b""
        while True:
            rlist, _, _ = select.select([fd], [], [], 0.05)
            if not rlist:
                break
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            self._cumulative[session_id] = self._cumulative.get(session_id, 0) + len(chunk)
            if len(out) >= self.max_bytes:
                break

        text = out.decode(errors="ignore")
        truncated_text, truncated = truncate_output(text, max_bytes=self.max_bytes, max_lines=self.max_lines)
        cumulative = self._cumulative.get(session_id, 0)
        if truncated or cumulative > self.max_bytes:
            truncated = True
            if not truncated_text.endswith("[truncated]"):
                if not truncated_text.endswith("\n"):
                    truncated_text += "\n"
                truncated_text += "[truncated]"
        return {"output": truncated_text, "truncated": truncated}


class ExecCommandInput(ToolRequest):
    session_id: str = Field(description="Opaque PTY session identifier.")
    cmd: str = Field(description="Command to execute in PTY.")
    workdir: str | Path | None = Field(default=None, description="Working directory (optional).")


class ExecCommandOutput(ToolResponse):
    output: str
    truncated: bool


class WriteStdinInput(ToolRequest):
    session_id: str = Field(description="Existing PTY session id.")
    chars: str = Field(description="Characters to write to stdin.")


class WriteStdinOutput(ToolResponse):
    output: str
    truncated: bool


def tool_registrations(boundary: FsBoundary, pty_manager: PtyManager | None = None) -> list[ToolRegistration]:
    manager = pty_manager or PtyManager(boundary)

    def _end_event(validated: BaseModel, output: BaseModel) -> dict[str, object]:
        return {
            "session_id": getattr(validated, "session_id", None),
            "truncated": getattr(output, "truncated", None),
        }

    class ExecTool(Tool[ExecCommandInput, ExecCommandOutput]):
        name = "exec_command"
        description = "Run a PTY-backed long command"
        InputModel = ExecCommandInput
        OutputModel = ExecCommandOutput
        requires_approval = True

        def __init__(self, mgr: PtyManager) -> None:
            self.mgr = mgr

        def execute(self, request: ExecCommandInput) -> ExecCommandOutput:
            return ExecCommandOutput.model_validate(self.mgr.exec_command(**request.model_dump()))

    class WriteStdinTool(Tool[WriteStdinInput, WriteStdinOutput]):
        name = "write_stdin"
        description = "Send input to existing PTY session"
        InputModel = WriteStdinInput
        OutputModel = WriteStdinOutput
        requires_approval = True

        def __init__(self, mgr: PtyManager) -> None:
            self.mgr = mgr

        def execute(self, request: WriteStdinInput) -> WriteStdinOutput:
            return WriteStdinOutput.model_validate(self.mgr.write_stdin(**request.model_dump()))

    exec_tool = ExecTool(manager)
    write_tool = WriteStdinTool(manager)

    return [
        ToolRegistration(
            name="exec_command",
            description="Run a PTY-backed long command",
            input_model=ExecCommandInput,
            output_model=ExecCommandOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], exec_tool.execute),
            requires_approval=True,
            end_event_builder=_end_event,
        ),
        ToolRegistration(
            name="write_stdin",
            description="Send input to existing PTY session",
            input_model=WriteStdinInput,
            output_model=WriteStdinOutput,
            handler=cast(Callable[[ToolRequest], ToolResponse], write_tool.execute),
            requires_approval=True,
            end_event_builder=_end_event,
        ),
    ]


__all__ = [
    "PtyManager",
    "PtySession",
    "tool_registrations",
    "ExecCommandInput",
    "ExecCommandOutput",
    "WriteStdinInput",
    "WriteStdinOutput",
]
