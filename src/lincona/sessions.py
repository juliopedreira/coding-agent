"""Session utilities: IDs, JSONL persistence, and session helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class Event(BaseModel):
    """Validated session event line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    event_type: str
    id: UUID
    trace_id: UUID | None = None
    role: Role
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tool_name: str | None = None


def generate_session_id(now: datetime | None = None) -> str:
    """Return a session id in the form YYYYMMDDHHMM-uuid4.

    ``now`` exists to ease testing and determinism; it defaults to current UTC.
    """

    instant = now or datetime.now(UTC)
    timestamp = instant.strftime("%Y%m%d%H%M")
    return f"{timestamp}-{uuid4()}"


class JsonlEventWriter:
    """Append-only JSONL writer for session events."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        self._closed = False

    def append(self, event: Event) -> None:
        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._closed = True

    def __enter__(self) -> JsonlEventWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def iter_events(path: Path | str) -> Iterator[Event]:
    """Yield validated events from a JSONL file.

    Blank lines are skipped; malformed or invalid lines raise ``ValidationError``
    from Pydantic or ``json.JSONDecodeError``.
    """

    for line in Path(path).open("r", encoding="utf-8"):
        stripped = line.strip()
        if not stripped:
            continue
        yield Event.model_validate_json(stripped)


SESSIONS_DIR = Path.home() / ".lincona" / "sessions"


def session_path(session_id: str, base_dir: Path | None = None) -> Path:
    directory = base_dir or SESSIONS_DIR
    return directory / f"{session_id}.jsonl"


class SessionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    path: Path
    modified_at: datetime
    size_bytes: int


def list_sessions(base_dir: Path | None = None) -> list[SessionInfo]:
    directory = base_dir or SESSIONS_DIR
    if not directory.exists():
        return []

    entries: list[SessionInfo] = []
    for path in directory.glob("*.jsonl"):
        session_id = path.stem
        stat_result = path.stat()
        entries.append(
            SessionInfo(
                session_id=session_id,
                path=path,
                modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
                size_bytes=stat_result.st_size,
            )
        )

    # Most recent first
    entries.sort(key=lambda e: e.modified_at, reverse=True)
    return entries


def resume_session(session_id: str, base_dir: Path | None = None) -> Iterator[Event]:
    return iter_events(session_path(session_id, base_dir))


def delete_session(session_id: str, base_dir: Path | None = None) -> None:
    path = session_path(session_id, base_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return


__all__ = [
    "Role",
    "Event",
    "JsonlEventWriter",
    "iter_events",
    "generate_session_id",
    "SESSIONS_DIR",
    "session_path",
    "SessionInfo",
    "list_sessions",
    "resume_session",
    "delete_session",
]
