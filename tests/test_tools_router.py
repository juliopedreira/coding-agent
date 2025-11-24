import pytest

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.approval import ApprovalRequiredError
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter, tool_specs


def test_tool_specs_contains_tools() -> None:
    names = {spec["function"]["name"] for spec in tool_specs()}
    assert {"list_dir", "read_file", "grep_files", "apply_patch_freeform", "shell"}.issubset(names)


def test_dispatch_list_dir(tmp_path):
    (tmp_path / "a").mkdir()
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)

    entries = router.dispatch("list_dir", path=".", depth=1)

    assert "a/" in entries


def test_dispatch_apply_patch_honors_approval(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.ALWAYS)
    patch = """--- a/file.txt
+++ b/file.txt
@@ -0,0 +1,1 @@
+hi
"""
    with pytest.raises(ApprovalRequiredError):
        router.dispatch("apply_patch_json", patch=patch)


def test_dispatch_exec_command_uses_manager(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)
    result = router.dispatch("exec_command", session_id="s1", cmd="echo hi", workdir=tmp_path)

    assert "hi" in result["output"]


def test_dispatch_shell_blocked_by_approval(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.ALWAYS)

    with pytest.raises(ApprovalRequiredError):
        router.dispatch("shell", command="echo hi")


def test_dispatch_apply_patch_freeform(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: f.txt
@@ -1,1 +1,1 @@
-old
+new
*** End Patch"""

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)

    router.dispatch("apply_patch_freeform", patch=patch)

    assert target.read_text(encoding="utf-8") == "new\n"


def test_dispatch_apply_patch_json(tmp_path):
    patch = """--- a/new.txt
+++ b/new.txt
@@ -0,0 +1,1 @@
+hi
"""
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)

    router.dispatch("apply_patch_json", patch=patch)

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hi"
    assert router.events[-1]["files"] == 1


def test_dispatch_unknown_tool_raises(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)

    with pytest.raises(ValueError):
        router.dispatch("unknown_tool")


def test_dispatch_write_stdin(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)
    router.dispatch("exec_command", session_id="s2", cmd="cat")
    result = router.dispatch("write_stdin", session_id="s2", chars="ping\n")
    assert "ping" in result["output"]
    assert any(e for e in router.events if e["tool"] == "write_stdin" and e["phase"] == "end")
