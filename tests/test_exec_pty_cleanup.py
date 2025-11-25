import os

from lincona.config import FsMode
from lincona.tools.exec_pty import PtyManager
from lincona.tools.fs import FsBoundary


def test_close_handles_closed_fd(monkeypatch, tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    mgr = PtyManager(boundary)

    # Start a benign process
    result = mgr.exec_command("s1", "sleep 1", workdir=tmp_path)
    assert "output" in result

    # Manually close fd to force OSError on close
    session = mgr.sessions["s1"]
    os.close(session.fd)

    # Should not raise
    mgr.close("s1")


def test_close_all_is_resilient(tmp_path, monkeypatch):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    mgr = PtyManager(boundary)

    mgr.exec_command("s1", "sleep 1", workdir=tmp_path)
    mgr.exec_command("s2", "sleep 1", workdir=tmp_path)

    # Make one session invalid to trigger exception
    session = mgr.sessions["s1"]
    os.close(session.fd)

    # Should not raise despite one bad session\n+    mgr.close_all()
