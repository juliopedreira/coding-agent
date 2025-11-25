import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from lincona.sessions import (
    Event,
    JsonlEventWriter,
    Role,
    delete_session,
    generate_session_id,
    iter_events,
    list_sessions,
    resume_session,
    session_path,
)


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


def test_event_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Event(
            timestamp=datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
            event_type="message",
            id=UUID("12345678-1234-5678-1234-567812345678"),
            role=Role.USER,
            content="hi",
            metadata={},
            error=None,
            tool_name=None,
            extra_field="oops",  # type: ignore[arg-type]
        )


def test_event_schema_requires_fields() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate({"event_type": "message", "content": "hi"})


def test_session_list_resume_delete(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    base_dir.mkdir(parents=True, exist_ok=True)
    session_id = "202501020304-11111111-1111-4111-8111-111111111111"
    path = session_path(session_id, base_dir)

    event = sample_event()
    with JsonlEventWriter(path) as writer:
        writer.append(event)

    # Touch second file with older mtime to verify sorting
    older_id = "202401010101-22222222-2222-4222-8222-222222222222"
    older_path = session_path(older_id, base_dir)
    older_path.parent.mkdir(parents=True, exist_ok=True)
    older_path.write_text("", encoding="utf-8")
    past = datetime.now(UTC) - timedelta(days=1)
    mod_time = past.timestamp()
    os.utime(older_path, (mod_time, mod_time))

    sessions = list_sessions(base_dir)
    assert [s.session_id for s in sessions] == [session_id, older_id]
    assert sessions[0].path == path
    assert sessions[0].size_bytes == path.stat().st_size

    events = list(resume_session(session_id, base_dir))
    assert events == [event]

    delete_session(session_id, base_dir)
    assert not path.exists()
    assert not path.parent.exists()

    # Deleting again should be silent
    delete_session(session_id, base_dir)


def test_writer_recovers_after_close(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = JsonlEventWriter(path)
    writer.append(sample_event())
    writer.close()
    writer.append(sample_event())
    writer.close()
    events = list(iter_events(path))
    assert len(events) == 2


def test_session_paths_respect_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path))

    session_id = "202501020304-abc"
    expected = tmp_path / "sessions" / session_id / "events.jsonl"

    assert session_path(session_id) == expected
