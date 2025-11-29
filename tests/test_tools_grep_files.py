from pathlib import Path

import pytest

import lincona.tools.grep_files as grep_mod
from lincona.config import FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.grep_files import (
    FileMatches,
    GrepFilesInput,
    GrepFilesOutput,
    GrepFilesTool,
    LineMatch,
    grep_files,
    tool_registrations,
)


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


def test_grep_input_parses_include_string_json() -> None:
    validated = GrepFilesInput.model_validate({"pattern": "x", "include": '["*.py","*.md"]'})
    assert validated.include == ["*.py", "*.md"]


def test_grep_input_parses_include_csv_and_empty() -> None:
    validated = GrepFilesInput.model_validate({"pattern": "x", "include": "a.py, b.py"})
    assert validated.include == ["a.py", "b.py"]
    validated_empty = GrepFilesInput.model_validate({"pattern": "x", "include": " [] "})
    assert validated_empty.include is None


def test_grep_files_with_stubbed_iter(monkeypatch):
    class StubBoundary:
        def sanitize_path(self, path):
            return Path("/root")

        def assert_within_root(self, path):
            return None

        def root_path(self):
            return None

    class FakePath:
        def __init__(self, text: str):
            self._text = text

        def read_text(self, *a, **k):
            return self._text

        def resolve(self):
            return Path("/abs/file.txt")

        def is_file(self):
            return True

        def match(self, pattern):
            return True

    monkeypatch.setattr("lincona.tools.grep_files._iter_files", lambda root, include=None: [FakePath("hit\n")])
    results = grep_files(StubBoundary(), "hit")
    assert results[0].file == "/abs/file.txt"


def test_iter_files_skips_dirs(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "subdir").mkdir(parents=True, exist_ok=True)
    files = list(grep_mod._iter_files(root))
    assert files == []


def test_grep_tool_execute_and_end_event(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    monkeypatch.setattr(
        "lincona.tools.grep_files.grep_files",
        lambda boundary, **kwargs: [FileMatches(file="a", matches=[LineMatch(line_num=1, line="hit", truncated=None)])],
    )
    tool = GrepFilesTool(restricted_boundary)
    output = tool.execute(GrepFilesInput(pattern="hit"))
    assert isinstance(output, GrepFilesOutput)
    reg = tool_registrations(restricted_boundary)[0]
    event = reg.end_event_builder(GrepFilesInput(pattern="hit"), output)  # type: ignore[arg-type]
    assert event["matches"] == 1
