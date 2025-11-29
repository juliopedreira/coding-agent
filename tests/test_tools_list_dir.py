from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary, FsViolationError
from lincona.tools.list_dir import list_dir, ListDirTool, ListDirInput, tool_registrations


def test_lists_depth_and_limits(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file.txt").write_text("hi")
    (tmp_path / "b").mkdir()

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    entries = list_dir(boundary, path=".", depth=2, offset=0, limit=10)

    # markers: dirs have '/', symlinks '@', files none
    assert "a/" in entries
    assert "b/" in entries
    assert "a/file.txt" in entries


def test_respects_offset_and_limit(tmp_path: Path) -> None:
    for name in ["a", "b", "c", "d"]:
        (tmp_path / name).mkdir()

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    entries = list_dir(boundary, ".", depth=1, offset=1, limit=2)

    assert len(entries) == 2
    # Sorted alphabetically
    assert entries == ["b/", "c/"]


def test_blocks_escape(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(FsViolationError):
        list_dir(boundary, path="../etc", depth=1)


def test_symlink_marker(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    entries = list_dir(boundary, ".", depth=1)

    assert "link@" in entries


def test_not_a_directory_returns_empty(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("hi")

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    entries = list_dir(boundary, path="file.txt", depth=1)

    assert entries == []


def test_missing_path_returns_empty(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    entries = list_dir(boundary, path="missing", depth=1)
    assert entries == []


def test_unrestricted_returns_absolute_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boundary:
        def sanitize_path(self, path):
            return Path("/tmp/root")

        def assert_within_root(self, path):
            pass

        def root_path(self):
            return None

    child = Path("/tmp/root/child")
    monkeypatch.setattr(Path, "iterdir", lambda self: [child] if self == Path("/tmp/root") else [])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    entries = list_dir(Boundary(), path=".")
    assert entries == ["/tmp/root/child"]


def test_list_dir_tool_execute_and_end_event(monkeypatch: pytest.MonkeyPatch, restricted_boundary) -> None:
    monkeypatch.setattr("lincona.tools.list_dir.list_dir", lambda boundary, **kwargs: ["x/"])
    tool = ListDirTool(restricted_boundary)
    output = tool.execute(ListDirInput(path=".", depth=1))
    assert output.entries == ["x/"]
    reg = tool_registrations(restricted_boundary)[0]
    event = reg.end_event_builder(ListDirInput(path=".", depth=1), output)  # type: ignore[arg-type]
    assert event["count"] == 1
