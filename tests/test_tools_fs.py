from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary, FsViolationError


def test_restricted_resolves_relative_paths() -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("/tmp/root"))

    resolved = boundary.sanitize_path("foo/bar.txt")

    assert resolved == Path("/tmp/root/foo/bar.txt")
    boundary.assert_within_root(resolved)


def test_restricted_blocks_escape() -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=Path("/tmp/root"))

    with pytest.raises(FsViolationError):
        boundary.sanitize_path("../etc/passwd")


def test_unrestricted_allows_absolute() -> None:
    boundary = FsBoundary(FsMode.UNRESTRICTED)

    resolved = boundary.sanitize_path("/var/log/syslog")

    assert resolved == Path("/var/log/syslog")


def test_sanitize_workdir_defaults() -> None:
    root = Path("/tmp/root")
    boundary = FsBoundary(FsMode.RESTRICTED, root=root)
    assert boundary.sanitize_workdir(None) == root

    boundary_unrestricted = FsBoundary(FsMode.UNRESTRICTED)
    assert boundary_unrestricted.sanitize_workdir(None) == Path.cwd()


def test_sanitize_workdir_absolute_in_restricted() -> None:
    root = Path("/tmp/root")
    boundary = FsBoundary(FsMode.RESTRICTED, root=root)
    workdir = boundary.sanitize_workdir("/tmp/root/sub")
    assert workdir == Path("/tmp/root/sub")


def test_assert_within_root_unrestricted_noop() -> None:
    boundary = FsBoundary(FsMode.UNRESTRICTED)
    boundary.assert_within_root(Path("/etc/hosts"))  # should not raise


def test_root_path_accessor() -> None:
    restricted = FsBoundary(FsMode.RESTRICTED, root=Path("/tmp/root"))
    unrestricted = FsBoundary(FsMode.UNRESTRICTED)
    assert restricted.root_path() == Path("/tmp/root")
    assert unrestricted.root_path() is None
