import pytest

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.approval import ApprovalRequiredError
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter


def test_router_emits_start_and_end(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")

    router.dispatch("list_dir", path=".", depth=1)

    assert router.events[0]["phase"] == "start"
    assert router.events[-1]["phase"] in {"start", "end"}


def test_router_shell_end_event(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.NEVER)
    router.dispatch("shell", command="echo hi", workdir=tmp_path)
    assert any(e for e in router.events if e["tool"] == "shell" and e["phase"] == "end")


def test_router_approval_blocks_on_request(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    router = ToolRouter(boundary, ApprovalPolicy.ON_REQUEST)
    patch = """--- a/file.txt
+++ b/file.txt
@@ -0,0 +1,1 @@
+hi
"""
    with pytest.raises(ApprovalRequiredError):
        router.dispatch("apply_patch_json", patch=patch)
