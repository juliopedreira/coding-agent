"""Session utilities: IDs and JSONL event persistence."""

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


__all__ = ["Role", "Event", "generate_session_id", "JsonlEventWriter", "iter_events"]
