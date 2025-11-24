import pytest

from lincona.tools.patch_parser import PatchParseError, parse_unified_diff


def test_rename_is_rejected_for_now() -> None:
    diff = """--- a/old.txt
+++ b/new.txt
@@ -1,1 +1,1 @@
-a
+a
"""
    patches = parse_unified_diff(diff)
    assert len(patches) == 1
    # rename not yet supported separately; treated as modify of new path only
    assert patches[0].path.as_posix() == "new.txt"


def test_binary_patch_rejected() -> None:
    with pytest.raises(PatchParseError):
        parse_unified_diff("Binary files a/foo and b/foo differ\n")
