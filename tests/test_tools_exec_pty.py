from pathlib import Path
import os

import pytest

from lincona.config import FsMode
from lincona.tools.exec_pty import PtyManager, tool_registrations
from lincona.tools.fs import FsBoundary


def test_exec_command_outputs(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary, max_bytes=1024, max_lines=50)

    result = manager.exec_command("s1", "echo hello", workdir=tmp_path)

    assert "hello" in result["output"]
    assert result["truncated"] is False


def test_write_stdin_appends_output(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary)

    manager.exec_command("s2", "cat", workdir=tmp_path)
    result = manager.write_stdin("s2", "hi\n")

    assert "hi" in result["output"]


def test_missing_session_raises(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary)

    with pytest.raises(KeyError):
        manager.write_stdin("missing", "data")


def test_truncation_in_pty(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary, max_bytes=10, max_lines=2)

    result = manager.exec_command("s3", "printf '1234567890abcd'")

    assert result["truncated"] is True
    assert result["output"].endswith("[truncated]")


def test_close_all_clears_sessions(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary)
    manager.exec_command("s4", "echo hi", workdir=tmp_path)
    assert "s4" in manager.sessions
    manager.close_all()
    assert manager.sessions == {}


def test_close_fallbacks(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    dummy_proc = type(
        "P",
        (),
        {
            "terminate": lambda self=None: (_ for _ in ()).throw(RuntimeError("fail")),
            "kill": lambda self=None: (_ for _ in ()).throw(RuntimeError("failkill")),
            "wait": lambda self=None, timeout=2: None,
        },
    )()
    manager.sessions["sid"] = type("S", (), {"proc": dummy_proc, "fd": 1, "cwd": Path(".")})
    manager._cumulative["sid"] = 0
    manager.close("sid")
    assert "sid" not in manager.sessions


def test_close_missing_session_noop(tmp_path: Path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary)
    manager.close("missing")  # should not raise


def test_close_wait_exception(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    proc = type(
        "P",
        (),
        {
            "terminate": lambda self=None: None,
            "wait": lambda self=None, timeout=2: (_ for _ in ()).throw(RuntimeError("waitfail")),
            "kill": lambda self=None: None,
        },
    )()
    manager.sessions["sidw"] = type("S", (), {"proc": proc, "fd": 2, "cwd": Path(".")})
    manager._cumulative["sidw"] = 0
    manager.close("sidw")


def test_close_all_handles_exceptions(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    manager.sessions["x"] = type("S", (), {"proc": None, "fd": 0, "cwd": Path(".")})

    def boom(sid):
        raise RuntimeError("fail")

    monkeypatch.setattr(manager, "close", boom)
    manager.close_all()  # should swallow and continue


def test_close_handles_closed_fd(monkeypatch, tmp_path: Path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    mgr = PtyManager(boundary)
    result = mgr.exec_command("s1", "sleep 1", workdir=tmp_path)
    assert "output" in result
    session = mgr.sessions["s1"]
    import os

    os.close(session.fd)
    mgr.close("s1")  # should not raise


def test_read_handles_empty_chunk(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    manager.sessions["sid"] = type("S", (), {"proc": None, "fd": 123, "cwd": Path(".")})
    manager._cumulative["sid"] = 0

    monkeypatch.setattr("select.select", lambda fds, *_: (fds, [], []))
    monkeypatch.setattr("os.read", lambda fd, size: b"")
    result = manager._read("sid")
    assert result["output"] == ""
    assert result["truncated"] is False


def test_read_appends_truncated_marker(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary, max_bytes=5)
    manager.sessions["sid"] = type("S", (), {"proc": None, "fd": 123, "cwd": Path(".")})
    manager._cumulative["sid"] = 10

    monkeypatch.setattr("select.select", lambda fds, *_: ([], [], []))
    # force truncate_output to return text without marker
    monkeypatch.setattr("lincona.tools.exec_pty.truncate_output", lambda text, max_bytes, max_lines: ("abc", True))
    result = manager._read("sid")
    assert result["truncated"] is True
    assert result["output"].endswith("[truncated]")


def test_read_truncated_with_existing_newline(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary, max_bytes=5)
    manager.sessions["sid3"] = type("S", (), {"proc": None, "fd": 125, "cwd": Path(".")})
    manager._cumulative["sid3"] = manager.max_bytes + 1

    monkeypatch.setattr("select.select", lambda fds, *_: ([], [], []))
    monkeypatch.setattr("lincona.tools.exec_pty.truncate_output", lambda text, max_bytes, max_lines: ("hi\n", True))
    monkeypatch.setattr("os.read", lambda fd, size: b"")
    result = manager._read("sid3")
    assert result["output"].endswith("[truncated]")


def test_end_event_builder_handles_missing_session(tmp_path: Path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    regs = tool_registrations(boundary)
    end_builder = regs[0].end_event_builder
    dummy_validated = type("V", (), {"session_id": None})
    dummy_output = type("O", (), {"truncated": True})
    data = end_builder(dummy_validated, dummy_output)  # type: ignore[arg-type]
    assert data["session_id"] is None
