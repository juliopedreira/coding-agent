import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import lincona.tools.exec_pty as exec_mod
from lincona.config import FsMode
from lincona.tools.exec_pty import (
    ExecCommandInput,
    ExecCommandOutput,
    ExecTool,
    PtyManager,
    WriteStdinInput,
    WriteStdinTool,
    tool_registrations,
)
from lincona.tools.fs import FsBoundary


@pytest.fixture
def fake_pty(monkeypatch: pytest.MonkeyPatch):
    """Stub out PTY creation and process spawning to avoid real OS interaction."""

    proc = SimpleNamespace(
        returncode=None,
        terminate=lambda self=None: None,
        kill=lambda self=None: None,
        wait=lambda self=None, timeout=2: None,
    )
    monkeypatch.setattr(exec_mod.pty, "openpty", lambda: (11, 12))
    monkeypatch.setattr(exec_mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(exec_mod.os, "close", lambda fd: None)
    return proc


def test_exec_command_outputs(restricted_boundary, monkeypatch: pytest.MonkeyPatch, fake_pty) -> None:
    manager = PtyManager(restricted_boundary, max_bytes=1024, max_lines=50)
    monkeypatch.setattr(manager, "_read", lambda sid: {"output": "hello", "truncated": False})

    result = manager.exec_command("s1", "echo hello", workdir=".")

    assert result["output"] == "hello"
    assert manager.sessions["s1"].proc is fake_pty


def test_write_stdin_appends_output(restricted_boundary, monkeypatch: pytest.MonkeyPatch, fake_pty) -> None:
    manager = PtyManager(restricted_boundary)
    monkeypatch.setattr(exec_mod.os, "write", lambda fd, data: len(data))
    responses = iter(
        [
            {"output": "init", "truncated": False},
            {"output": "hi", "truncated": False},
        ]
    )
    monkeypatch.setattr(manager, "_read", lambda sid: next(responses))

    manager.exec_command("s2", "cat", workdir=".")
    result = manager.write_stdin("s2", "hi\n")

    assert result["output"] == "hi"


def test_missing_session_raises(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    manager = PtyManager(boundary)

    with pytest.raises(KeyError):
        manager.write_stdin("missing", "data")


def test_truncation_in_pty(restricted_boundary, monkeypatch: pytest.MonkeyPatch, fake_pty) -> None:
    manager = PtyManager(restricted_boundary, max_bytes=10, max_lines=2)
    monkeypatch.setattr(manager, "_read", lambda sid: {"output": "123\n[truncated]", "truncated": True})

    result = manager.exec_command("s3", "ignored")

    assert result["truncated"] is True
    assert result["output"].endswith("[truncated]")


def test_close_all_clears_sessions(restricted_boundary, fake_pty, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = PtyManager(restricted_boundary)
    monkeypatch.setattr(manager, "_read", lambda sid: {"output": "", "truncated": False})
    manager.exec_command("s4", "echo hi", workdir=".")
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


def test_close_handles_closed_fd(monkeypatch, restricted_boundary, fake_pty):
    mgr = PtyManager(restricted_boundary)
    monkeypatch.setattr(mgr, "_read", lambda sid: {"output": "", "truncated": False})
    mgr.exec_command("s1", "sleep 1", workdir=".")
    monkeypatch.setattr(os, "close", lambda fd: None)
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


def test_exec_command_input_casts_path_workdir():
    validated = ExecCommandInput.model_validate({"session_id": "s", "cmd": "echo", "workdir": Path("/tmp/work")})
    assert isinstance(validated.workdir, str)


def test_read_breaks_on_os_error(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    manager.sessions["err"] = type("S", (), {"proc": None, "fd": 55, "cwd": Path(".")})
    manager._cumulative["err"] = 0
    monkeypatch.setattr("select.select", lambda fds, *_: (fds, [], []))
    monkeypatch.setattr("os.read", lambda fd, size: (_ for _ in ()).throw(OSError("bad fd")))
    result = manager._read("err")
    assert result["output"] == ""


def test_read_accumulates_and_marks_truncated(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary, max_bytes=2, max_lines=10)
    manager.sessions["sidacc"] = type("S", (), {"proc": None, "fd": 77, "cwd": Path(".")})
    manager._cumulative["sidacc"] = 0
    monkeypatch.setattr("select.select", lambda fds, *_: (fds, [], []))
    monkeypatch.setattr("os.read", lambda fd, size: b"abc")
    monkeypatch.setattr("lincona.tools.exec_pty.truncate_output", lambda text, max_bytes, max_lines: (text, False))
    result = manager._read("sidacc")
    assert result["output"].endswith("[truncated]")


def test_close_handles_os_error(monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("."))
    manager = PtyManager(boundary)
    manager.sessions["sid"] = type(
        "S",
        (),
        {
            "proc": SimpleNamespace(terminate=lambda: None, wait=lambda timeout=2: None, kill=lambda: None),
            "fd": 90,
            "cwd": Path("."),
        },
    )
    manager._cumulative["sid"] = 0
    monkeypatch.setattr("lincona.tools.exec_pty.os.close", lambda fd: (_ for _ in ()).throw(OSError("closed")))
    manager.close("sid")
    assert "sid" not in manager.sessions


def test_exec_and_write_tools_use_manager(monkeypatch):
    class DummyMgr:
        def exec_command(self, **kwargs):
            return {"output": "ok", "truncated": False}

        def write_stdin(self, **kwargs):
            return {"output": "pong", "truncated": False}

    mgr = DummyMgr()
    exec_tool = ExecTool(mgr)  # type: ignore[arg-type]
    write_tool = WriteStdinTool(mgr)  # type: ignore[arg-type]
    exec_output = exec_tool.execute(ExecCommandInput(session_id="s", cmd="echo", workdir="."))
    write_output = write_tool.execute(WriteStdinInput(session_id="s", chars="hi"))
    assert exec_output.output == "ok" and write_output.output == "pong"


def test_end_event_builder_with_session(monkeypatch, restricted_boundary):
    manager = PtyManager(restricted_boundary)
    regs = tool_registrations(restricted_boundary, manager)
    manager.sessions["s"] = SimpleNamespace(proc=SimpleNamespace(returncode=5), fd=1, cwd=Path("."))
    validated = ExecCommandInput(session_id="s", cmd="echo", workdir=".")
    output = ExecCommandOutput(output="", truncated=False)
    event = regs[0].end_event_builder(validated, output)  # type: ignore[arg-type]
    assert event["returncode"] == 5 and event["session_id"] == "s"
