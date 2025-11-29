import pytest

from lincona.tools.patch_parser import (
    FREEFORM_BEGIN,
    FREEFORM_END,
    PatchParseError,
    extract_freeform,
    parse_unified_diff,
)


def test_extract_freeform_ok() -> None:
    text = f"""{FREEFORM_BEGIN}
@@ -1,1 +1,1 @@
-old
+new
{FREEFORM_END}"""

    diff = extract_freeform(text)
    assert "@@ -1,1 +1,1 @@" in diff


def test_extract_freeform_missing_raises() -> None:
    with pytest.raises(PatchParseError):
        extract_freeform("no markers here")


def test_parse_unified_diff_parses_file_and_hunk() -> None:
    diff = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,2 @@
-old
+new
+line2
"""
    patches = parse_unified_diff(diff)

    assert len(patches) == 1
    fp = patches[0]
    assert fp.path.name == "file.txt"
    assert len(fp.hunks) == 1
    h = fp.hunks[0]
    assert h.start_old == 1
    assert h.start_new == 1
    assert h.lines[0].startswith("-")


def test_parse_unified_diff_errors_on_invalid_hunk() -> None:
    diff = """--- a/file.txt
+++ b/file.txt
@@ invalid
"""
    with pytest.raises(PatchParseError):
        parse_unified_diff(diff)


def test_parse_normalizes_prefixes() -> None:
    diff = """--- a/dir/file.txt
+++ b/dir/file.txt
@@ -0,0 +1,1 @@
+hi
"""
    patches = parse_unified_diff(diff)
    assert patches[0].path.as_posix() == "dir/file.txt"


def test_parse_update_file_header() -> None:
    diff = """*** Update File: dir/file.txt
@@ -0,0 +1,1 @@
+hi
"""
    patches = parse_unified_diff(diff)
    assert patches[0].path.as_posix() == "dir/file.txt"


def test_delete_file_header_sets_delete_flag():
    diff = """*** Delete File: path/to/file.txt"""
    patches = parse_unified_diff(diff)
    assert patches[0].delete is True
    assert patches[0].path.as_posix() == "path/to/file.txt"


def test_rename_treated_as_modify_path() -> None:
    diff = """--- a/old.txt
+++ b/new.txt
@@ -1,1 +1,1 @@
-a
+a
"""
    patches = parse_unified_diff(diff)
    assert patches[0].path.as_posix() == "new.txt"


def test_parse_missing_plus_header_raises() -> None:
    diff = """--- a/file.txt
@@ -0,0 +1,1 @@
+hi
"""
    with pytest.raises(PatchParseError):
        parse_unified_diff(diff)


def test_parse_no_hunks_raises() -> None:
    diff = """*** Update File: file.txt
"""
    with pytest.raises(PatchParseError):
        parse_unified_diff(diff)


def test_parse_no_patches_found() -> None:
    with pytest.raises(PatchParseError):
        parse_unified_diff("just text")


def test_parse_multiple_hunks_breaks_correctly() -> None:
    diff = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,2 @@
-old
+new
@@ -3,1 +3,1 @@
-tail
+tail
"""
    patches = parse_unified_diff(diff)
    assert len(patches[0].hunks) == 2


def test_unified_diff_no_hunks_raises() -> None:
    diff = """--- a/file.txt
+++ b/file.txt
"""
    with pytest.raises(PatchParseError):
        parse_unified_diff(diff)
