import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from lincona.sessions import Event, JsonlEventWriter, Role, generate_session_id, iter_events


def sample_event(ts: datetime | None = None) -> Event:
    return Event(
        timestamp=ts or datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
        event_type="message",
        id=UUID("12345678-1234-5678-1234-567812345678"),
        trace_id=None,
        role=Role.USER,
        content="hello",
        metadata={"foo": "bar"},
        error=None,
        tool_name=None,
    )


def test_generate_session_id_format_and_uniqueness() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)

    session_id = generate_session_id(now)

    assert session_id.startswith("202501020304-")
    uuid_part = session_id.split("-", maxsplit=1)[1]
    UUID(uuid_part)  # validates UUID format

    # successive calls should differ
    assert generate_session_id(now) != generate_session_id(now)


def test_jsonl_writer_and_iter_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    event = sample_event()

    with JsonlEventWriter(path) as writer:
        writer.append(event)

    events = list(iter_events(path))

    assert events == [event]


def test_writer_appends_without_truncating(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    first = sample_event()
    second = sample_event(datetime(2025, 1, 2, 3, 10, 0, tzinfo=UTC))

    with JsonlEventWriter(path) as writer:
        writer.append(first)

    with JsonlEventWriter(path) as writer:
        writer.append(second)

    events = list(iter_events(path))
    assert events == [first, second]


def test_iter_events_raises_on_invalid_line(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises((ValidationError, json.JSONDecodeError)):
        list(iter_events(path))
