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


def test_jsonl_writer_fsync_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path, fsync_every=1)
    event = sample_event()
    writer.append(event)
    writer.sync()
    writer.close()
    # reopen after close to hit _ensure_open
    writer.append(event)
    writer.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 2


def test_iter_events_skips_blank(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n", encoding="utf-8")
    assert list(iter_events(events_path)) == []


def test_list_sessions_nonexistent_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path / "missing"))
    assert list_sessions() == []


def test_list_sessions_skips_non_dir_and_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path))
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    (sessions_root / "random.txt").write_text("x", encoding="utf-8")  # not a dir
    missing_dir = sessions_root / "empty"
    missing_dir.mkdir()
    # no events.jsonl inside, should skip
    assert list_sessions() == []


def test_delete_session_handles_dir_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path))
    base = session_path("sid1")
    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / "events.jsonl").write_text("{}", encoding="utf-8")
    # create nested directory to trigger IsADirectoryError in unlink
    (base.parent / "subdir").mkdir()
    delete_session("sid1")
    # events file removed, directory still present because subdir blocks rmdir
    assert not (base.parent / "events.jsonl").exists()
    assert base.parent.exists()


def test_delete_session_rmdir_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINCONA_HOME", str(tmp_path))
    base = session_path("sid2")
    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / "events.jsonl").write_text("{}", encoding="utf-8")

    called = {}

    def fake_rmdir(self):
        called["rmdir"] = True
        raise OSError("busy")

    monkeypatch.setattr(Path, "rmdir", fake_rmdir, raising=False)
    delete_session("sid2")
    assert called["rmdir"] is True


def test_close_is_idempotent(tmp_path: Path) -> None:
    writer = JsonlEventWriter(tmp_path / "events.jsonl")
    writer.close()
    writer.close()  # should early-return
