import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import lincona.tools.apply_patch as apply_patch_mod
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


def test_delete_branch_appends_result(tmp_path: Path, mock_parse_unified_diff) -> None:
    target = tmp_path / "del.txt"
    target.write_text("bye", encoding="utf-8")
    from lincona.tools.patch_parser import FilePatch

    fp = FilePatch(path=Path("del.txt"), hunks=[], delete=True)
    mock_parse_unified_diff(return_value=[fp])
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    results = apply_patch(boundary, "ignored")
    assert results and results[0].bytes_written == 0 and results[0].created is False


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


def test_modify_nonexistent_raises(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    patch = """--- a/missing.txt
+++ b/missing.txt
@@ -1,1 +1,1 @@
-old
+new
"""
    with pytest.raises(PatchApplyError):
        apply_patch(boundary, patch)


def test_freeform_requires_hunk_content(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    patch = """*** Begin Patch
*** Update File: file.txt
@@
*** End Patch"""

    with pytest.raises(PatchParseError):
        apply_patch(boundary, patch, freeform=True)


def test_skip_dev_null_deletion(mock_parse_unified_diff, tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    fp = SimpleNamespace(delete=True, path=Path("/dev/null"), hunks=[])
    mock_parse_unified_diff(return_value=[fp])
    assert apply_patch(boundary, "ignored") == []


def test_cleanup_tempfile_on_replace_error(mocker, mock_parse_unified_diff, mock_path_replace, tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    fp = SimpleNamespace(delete=False, path=Path("err.txt"), hunks=[])
    mock_parse_unified_diff(return_value=[fp])

    created: dict[str, Path] = {}

    real_namedtemp = tempfile.NamedTemporaryFile

    def fake_namedtemp(*args, **kwargs):
        tmp = real_namedtemp(*args, **kwargs)
        created["path"] = Path(tmp.name)
        return tmp

    mocker.patch.object(apply_patch_mod.tempfile, "NamedTemporaryFile", autospec=True, side_effect=fake_namedtemp)

    def fake_replace(self, other):
        raise RuntimeError("boom")

    mock_path_replace(side_effect=fake_replace)

    with pytest.raises(RuntimeError):
        apply_patch(boundary, "ignored")

    assert "path" in created and not created["path"].exists()


def test_cleanup_tempfile_unlink_failure(mocker, mock_parse_unified_diff, mock_path_replace, tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    fp = SimpleNamespace(delete=False, path=Path("err2.txt"), hunks=[])
    mock_parse_unified_diff(return_value=[fp])

    real_namedtemp = tempfile.NamedTemporaryFile
    created: dict[str, Path] = {}

    def fake_namedtemp(*args, **kwargs):
        tmp = real_namedtemp(*args, **kwargs)
        created["path"] = Path(tmp.name)
        return tmp

    mocker.patch.object(apply_patch_mod.tempfile, "NamedTemporaryFile", autospec=True, side_effect=fake_namedtemp)
    mocker.patch.object(
        Path, "replace", autospec=True, side_effect=lambda self, other: (_ for _ in ()).throw(RuntimeError("boom2"))
    )
    mocker.patch.object(
        Path,
        "unlink",
        autospec=True,
        side_effect=lambda self, missing_ok=False: (_ for _ in ()).throw(RuntimeError("unlink")),
    )

    with pytest.raises(RuntimeError):
        apply_patch(boundary, "ignored2")

    assert "path" in created


def test_apply_hunks_context_and_invalid_line() -> None:
    hunk = apply_patch_mod.Hunk(start_old=1, len_old=1, start_new=1, len_new=1, lines=[" different"])
    with pytest.raises(apply_patch_mod.PatchApplyError):
        apply_patch_mod._apply_hunks(["orig"], [hunk])

    bad = apply_patch_mod.Hunk(start_old=1, len_old=1, start_new=1, len_new=1, lines=["?bad"])
    with pytest.raises(apply_patch_mod.PatchApplyError):
        apply_patch_mod._apply_hunks(["orig"], [bad])


def test_convert_results_and_end_event(tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    regs = apply_patch_mod.tool_registrations(boundary)
    # result_adapter should convert PatchResult objects to dicts
    res = apply_patch_mod.PatchResultModel(path="x", bytes_written=1, created=True)
    adapter = regs[0].result_adapter
    converted = adapter(apply_patch_mod.ApplyPatchOutput(results=[res]))  # type: ignore[arg-type]
    assert converted[0]["created"] is True
    end_output = apply_patch_mod.ApplyPatchOutput(
        results=[apply_patch_mod.PatchResultModel(path="p", bytes_written=1, created=False)]
    )
    end = regs[0].end_event_builder(None, end_output)  # type: ignore[arg-type]
    assert end == {"files": 1}


def test_join_preserve_trailing_adds_newline_when_missing() -> None:
    text = apply_patch_mod._join_preserve_trailing(["line"], had_trailing=True)
    assert text.endswith("\n")


def test_join_preserve_trailing_no_lines() -> None:
    text = apply_patch_mod._join_preserve_trailing([], had_trailing=True)
    assert text == ""


def test_apply_hunks_success_and_additions() -> None:
    hunk = apply_patch_mod.Hunk(
        start_old=1,
        len_old=1,
        start_new=2,
        len_new=2,
        lines=[" line1", "+added"],
    )
    result = apply_patch_mod._apply_hunks(["line1"], [hunk])
    assert result == ["line1", "added"]


def test_apply_patch_deletion_and_cleanup_and_helpers(
    mocker, mock_parse_unified_diff, mock_path_replace, tmp_path: Path
) -> None:
    from lincona.tools.patch_parser import FilePatch, Hunk

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    # deletion branch with existing file
    (tmp_path / "todel.txt").write_text("bye", encoding="utf-8")
    delete_patch = FilePatch(path=Path("todel.txt"), hunks=[], delete=True)
    parse_mock = mock_parse_unified_diff(return_value=[delete_patch])
    res = apply_patch(boundary, "ignored")
    assert res[0].bytes_written == 0 and res[0].created is False

    # error cleanup branch after temp file created
    (tmp_path / "good.txt").write_text("", encoding="utf-8")
    hunk = Hunk(start_old=0, len_old=0, start_new=1, len_new=1, lines=["+hi"])
    good_patch = FilePatch(path=Path("good.txt"), hunks=[hunk], delete=False)

    def fake_replace(self, target):
        raise RuntimeError("boom")

    parse_mock.return_value = [good_patch]
    mock_path_replace(side_effect=fake_replace)
    with pytest.raises(RuntimeError):
        apply_patch(boundary, "ignored-again")

    # result adapter helper
    regs = apply_patch_mod.tool_registrations(boundary)
    adapter = regs[0].result_adapter
    converted_output = apply_patch_mod.ApplyPatchOutput(
        results=[apply_patch_mod.PatchResultModel(path="p", bytes_written=1, created=True)]
    )
    converted = adapter(converted_output)  # type: ignore[arg-type]
    assert converted[0]["created"] is True

    # trailing newline helper
    assert apply_patch_mod._join_preserve_trailing(["line"], had_trailing=True).endswith("\n")


def test_apply_patch_delete_branch_only(mock_parse_unified_diff, tmp_path: Path) -> None:
    from lincona.tools.patch_parser import FilePatch

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    target = tmp_path / "delete_me.txt"
    target.write_text("bye", encoding="utf-8")
    mock_parse_unified_diff(return_value=[FilePatch(path=Path("delete_me.txt"), hunks=[], delete=True)])
    res = apply_patch(boundary, "ignored")
    assert res[0].bytes_written == 0 and not target.exists()


def test_apply_patch_cleanup_branch(mocker, mock_parse_unified_diff, mock_path_replace, tmp_path: Path) -> None:
    from lincona.tools.patch_parser import FilePatch, Hunk

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    target = tmp_path / "cleanup.txt"
    target.write_text("", encoding="utf-8")
    hunk = Hunk(start_old=0, len_old=0, start_new=1, len_new=1, lines=["+line"])
    patch = FilePatch(path=Path("cleanup.txt"), hunks=[hunk], delete=False)

    def fake_replace(self, target):
        raise RuntimeError("boom2")

    mock_parse_unified_diff(return_value=[patch])
    mock_path_replace(side_effect=fake_replace)
    with pytest.raises(RuntimeError):
        apply_patch(boundary, "ignored")


def test_convert_results_closure_and_apply_hunks_branches(tmp_path: Path) -> None:
    from inspect import getclosurevars

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    regs = apply_patch_mod.tool_registrations(boundary)
    adapter = regs[0].result_adapter
    closure_vars = getclosurevars(adapter)
    convert = closure_vars.nonlocals["_convert_results"]

    out = apply_patch_mod.ApplyPatchOutput(
        results=[apply_patch_mod.PatchResultModel(path="p", bytes_written=1, created=False)]
    )
    assert convert(out) is out  # ApplyPatchOutput passthrough

    # list[PatchResult] path
    pr = apply_patch_mod.PatchResult(path=tmp_path / "p", bytes_written=2, created=True)
    converted = convert([pr])
    assert converted.results[0].bytes_written == 2


def test_apply_patch_delete_branch_nonexistent(mocker, tmp_path: Path) -> None:
    from lincona.tools.patch_parser import FilePatch

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    mocker.patch.object(
        apply_patch_mod,
        "parse_unified_diff",
        autospec=True,
        return_value=[FilePatch(path=Path("missing.txt"), hunks=[], delete=True)],
    )
    results = apply_patch(boundary, "ignored")
    assert results == []


def test_apply_patch_cleanup_branch_tmp_none(mocker, tmp_path: Path) -> None:
    from lincona.tools.patch_parser import FilePatch, Hunk

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    hunk = Hunk(start_old=0, len_old=0, start_new=1, len_new=1, lines=["+line"])
    patch = FilePatch(path=Path("cleanup2.txt"), hunks=[hunk], delete=False)

    def fake_namedtemp(*args, **kwargs):
        raise RuntimeError("fail temp")

    mocker.patch.object(apply_patch_mod, "parse_unified_diff", autospec=True, return_value=[patch])
    mocker.patch.object(apply_patch_mod.tempfile, "NamedTemporaryFile", autospec=True, side_effect=fake_namedtemp)
    with pytest.raises(RuntimeError):
        apply_patch(boundary, "ignored")


def test_join_preserve_trailing_existing_newline() -> None:
    text = apply_patch_mod._join_preserve_trailing(["line\n"], had_trailing=True)
    assert text.endswith("\n")

    # cover _apply_hunks branches: context match and addition
    from lincona.tools.patch_parser import Hunk

    hunk = Hunk(start_old=1, len_old=1, start_new=1, len_new=2, lines=[" line", "+add"])
    result = apply_patch_mod._apply_hunks(["line"], [hunk])
    assert result == ["line", "add"]


def test_preserve_trailing_newline_when_missing_in_patch(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("line\n", encoding="utf-8")
    patch = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-line
+line"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    apply_patch(boundary, patch)
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_apply_patch_cleans_temp_on_replace_failure(mocker, tmp_path: Path) -> None:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    tool = apply_patch_mod.ApplyPatchTool(boundary)

    patch = """--- a/x.txt\n+++ b/x.txt\n@@ -0,0 +1,1 @@\n+hi\n"""

    class FailingPath(Path):
        _flavour = Path()._flavour

        def replace(self, target):  # type: ignore[override]
            raise OSError("simulated replace failure")

    mocker.patch.object(apply_patch_mod, "Path", FailingPath)

    with pytest.raises(OSError):
        tool.execute(apply_patch_mod.ApplyPatchInput(patch=patch))

    leftovers = list(tmp_path.rglob("*"))
    assert leftovers == []


def test_delete_mismatch_raises(tmp_path: Path) -> None:
    original = ["keep"]
    hunk = SimpleNamespace(start_old=1, lines=["-missing"])
    with pytest.raises(PatchApplyError):
        apply_patch_mod._apply_hunks(original, [hunk])


def test_join_preserve_trailing_adds_newline() -> None:
    text = apply_patch_mod._join_preserve_trailing(["line"], had_trailing=True)
    assert text.endswith("\n")
