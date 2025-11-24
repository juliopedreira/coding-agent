from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.exec_pty import PtyManager
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
