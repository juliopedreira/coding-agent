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

from lincona.paths import get_lincona_home


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

    def __init__(self, path: Path | str, *, fsync_every: int | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        self._closed = False
        self._fsync_every = fsync_every
        self._since_fsync = 0

    def append(self, event: Event) -> None:
        self._ensure_open()
        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        if self._fsync_every is not None:
            self._since_fsync += 1
            if self._since_fsync >= self._fsync_every:
                os.fsync(self._file.fileno())
                self._since_fsync = 0

    def sync(self) -> None:
        """Force flush and fsync regardless of fsync_every settings."""

        self._ensure_open()
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        if self._closed:
            return
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._closed = True

    def _ensure_open(self) -> None:
        """Re-open the underlying file if it was closed."""

        if self._closed or self._file.closed:
            self._file = self.path.open("a", encoding="utf-8")
            self._closed = False

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


def session_dir(session_id: str, base_dir: Path | None = None) -> Path:
    base = base_dir or (get_lincona_home() / "sessions")
    return base / session_id


def session_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Return the events JSONL path for a session inside its dedicated folder."""

    return session_dir(session_id, base_dir) / "events.jsonl"


class SessionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    path: Path
    modified_at: datetime
    size_bytes: int


def list_sessions(base_dir: Path | None = None) -> list[SessionInfo]:
    root = base_dir or (get_lincona_home() / "sessions")
    if not root.exists():
        return []

    entries: list[SessionInfo] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        path = directory / "events.jsonl"
        if not path.exists():
            continue
        stat_result = path.stat()
        entries.append(
            SessionInfo(
                session_id=directory.name,
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
    directory = session_dir(session_id, base_dir)
    if not directory.exists():
        return
    for item in directory.iterdir():
        try:
            item.unlink()
        except IsADirectoryError:
            continue
    try:
        directory.rmdir()
    except OSError:
        return


__all__ = [
    "Role",
    "Event",
    "JsonlEventWriter",
    "iter_events",
    "generate_session_id",
    "session_path",
    "session_dir",
    "SessionInfo",
    "list_sessions",
    "resume_session",
    "delete_session",
]
