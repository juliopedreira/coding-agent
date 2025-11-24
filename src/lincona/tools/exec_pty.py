"""Minimal PTY-backed exec manager."""

from __future__ import annotations

import os
import pty
import select
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lincona.tools.fs import FsBoundary
from lincona.tools.limits import truncate_output


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
            if len(out) >= self.max_bytes:
                break

        text = out.decode(errors="ignore")
        truncated_text, truncated = truncate_output(text, max_bytes=self.max_bytes, max_lines=self.max_lines)
        return {"output": truncated_text, "truncated": truncated}


__all__ = ["PtyManager", "PtySession"]
