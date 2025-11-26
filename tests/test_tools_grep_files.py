from pathlib import Path

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.grep_files import grep_files


def test_grep_matches_and_limit(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("hello\nworld\nhello again\n", encoding="utf-8")
    file2 = tmp_path / "b.md"
    file2.write_text("nothing here\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = grep_files(boundary, r"hello", path=".", limit=1)

    assert len(results) == 1
    assert results[0].file == "a.txt"
    assert results[0].matches[0].line_num == 1


def test_grep_include_glob(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("match\n", encoding="utf-8")
    file2 = tmp_path / "b.log"
    file2.write_text("match\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = grep_files(boundary, "match", include=["*.txt"])

    assert len(results) == 1
    assert results[0].file == "a.txt"
    assert results[0].matches[0].line == "match"


def test_grep_skips_non_dir_path(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("match\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = grep_files(boundary, "match", path="a.txt")

    assert results == []


def test_grep_include_filters_out(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("match\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = grep_files(boundary, "match", include=["*.md"])

    assert results == []


def test_grep_handles_read_error(monkeypatch, tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    file1.write_text("match\n", encoding="utf-8")
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    original_read = Path.read_text

    def fake_read(self: Path, *args, **kwargs):
        if self == file1:
            raise OSError("boom")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read)

    results = grep_files(boundary, "match")
    assert results == []


def test_grep_truncates_long_lines(tmp_path: Path) -> None:
    file1 = tmp_path / "a.txt"
    long_line = "x" * 1500
    file1.write_text(long_line + "\nshort\n", encoding="utf-8")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = grep_files(boundary, "x+", path=".")

    assert len(results) == 1
    match = results[0].matches[0]
    assert match.line.startswith("x" * 1000)
    assert match.truncated is True
