import pytest

from lincona.config import FsMode
from lincona.tools.apply_patch import PatchApplyError, apply_patch
from lincona.tools.fs import FsBoundary
from lincona.tools.patch_parser import PatchParseError


def test_modify_nonexistent_raises(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    patch = """--- a/missing.txt
+++ b/missing.txt
@@ -1,1 +1,1 @@
-old
+new
"""
    with pytest.raises(PatchApplyError):
        apply_patch(boundary, patch)


def test_directory_target_rejected(tmp_path):
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


def test_freeform_requires_hunk_content(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    patch = """*** Begin Patch
*** Update File: file.txt
@@
*** End Patch"""

    with pytest.raises(PatchParseError):
        apply_patch(boundary, patch, freeform=True)
