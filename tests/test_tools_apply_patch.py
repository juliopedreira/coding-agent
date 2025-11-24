from pathlib import Path

import pytest

from lincona.config import FsMode
from lincona.tools.apply_patch import PatchApplyError, apply_patch
from lincona.tools.fs import FsBoundary, FsViolationError
from lincona.tools.patch_parser import PatchParseError


def test_apply_simple_patch(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-old
+new
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    results = apply_patch(boundary, patch)

    assert target.read_text(encoding="utf-8") == "new\n"
    assert results[0].created is False


def test_apply_creates_file(tmp_path: Path) -> None:
    patch = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1,1 @@
+hello
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = apply_patch(boundary, patch)

    target = tmp_path / "new.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello"
    assert results[0].created is True


def test_apply_rejects_escape(tmp_path: Path) -> None:
    patch = """--- a/../etc/passwd
+++ b/../etc/passwd
@@ -1,0 +1,1 @@
+bad
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(FsViolationError):
        apply_patch(boundary, patch)


def test_apply_rejects_context_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("line\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-DIFFERENT
+line
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(PatchApplyError):
        apply_patch(boundary, patch)


def test_apply_freeform_envelope(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: file.txt
@@ -1,1 +1,1 @@
-old
+new
*** End Patch"""

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    apply_patch(boundary, patch, freeform=True)

    assert target.read_text(encoding="utf-8") == "new\n"


def test_delete_file(tmp_path: Path) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("bye", encoding="utf-8")
    patch = """--- a/gone.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-bye
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    apply_patch(boundary, patch)
    assert not target.exists()


def test_reject_binary_patch(tmp_path: Path) -> None:
    patch = "Binary files a/foo and b/foo differ\n"
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    with pytest.raises(PatchParseError):
        apply_patch(boundary, patch)


def test_preserves_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("line\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-line
+line
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    apply_patch(boundary, patch)
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_apply_directory_target_raises(tmp_path: Path) -> None:
    target_dir = tmp_path / "dir"
    target_dir.mkdir()
    patch = """--- a/dir
+++ b/dir
@@ -0,0 +1,1 @@
+oops
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(PatchApplyError):
        apply_patch(boundary, patch)


def test_hunk_start_out_of_range(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("hi\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -10,1 +10,1 @@
-hi
+bye
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(PatchApplyError):
        apply_patch(boundary, patch)


def test_invalid_hunk_line_prefix(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("hi\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
%bad
    """
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    with pytest.raises(PatchParseError):
        apply_patch(boundary, patch)
