from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.read_file import read_file


def test_reads_slice_and_truncates_lines(tmp_path: Path) -> None:
    text = "line0\n" + "x" * 500 + "\nline2\nline3\n"
    path = tmp_path / "f.txt"
    path.write_text(text, encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    content, truncated = read_file(boundary, "f.txt", offset=1, limit=2)

    assert truncated is True
    assert "… [truncated line]" in content


def test_indentation_mode(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    content, truncated = read_file(boundary, "f.txt", limit=2, mode="indentation", indent=">")

    assert content.startswith(">a\n>b")
    assert truncated is True


def test_read_file_missing_raises(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(FileNotFoundError):
        read_file(boundary, "missing.txt")


def test_invalid_mode_raises(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("x", encoding="utf-8")
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(ValueError):
        read_file(boundary, "f.txt", mode="invalid")
