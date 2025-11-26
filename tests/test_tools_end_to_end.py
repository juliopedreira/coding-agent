from pathlib import Path

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter


def make_router(tmp_path: Path) -> ToolRouter:
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    return ToolRouter(boundary, ApprovalPolicy.NEVER)


def test_list_dir_and_read_file(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")

    router = make_router(tmp_path)
    entries = router.dispatch("list_dir", path=".", depth=1)
    assert "file.txt" in entries

    text, truncated = router.dispatch("read_file", path="file.txt", offset=0, limit=10, mode="slice", indent="    ")
    assert "hello" in text
    assert truncated is False


def test_grep_files(tmp_path: Path):
    target = tmp_path / "a.txt"
    target.write_text("todo: fix\n", encoding="utf-8")
    router = make_router(tmp_path)

    results = router.dispatch("grep_files", pattern="todo", path=".", include=["*.txt"], limit=10)
    assert results
    assert results[0]["file"] == "a.txt"
    assert results[0]["matches"][0]["line_num"] == 1


def test_apply_patch_and_read_back(tmp_path: Path):
    patch = """--- a/new.txt
+++ b/new.txt
@@ -0,0 +1,1 @@
+hi
"""
    router = make_router(tmp_path)
    res = router.dispatch("apply_patch_json", patch=patch)
    assert any(entry.get("created") for entry in res)
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hi"


def test_shell_runs_command(tmp_path: Path):
    router = make_router(tmp_path)
    result = router.dispatch("shell", command="echo hi", workdir=str(tmp_path), timeout_ms=5000)
    assert result["stdout"].strip() == "hi"
    assert result["returncode"] == 0


def test_exec_and_write_stdin(tmp_path: Path):
    router = make_router(tmp_path)
    out1 = router.dispatch("exec_command", session_id="s1", cmd="cat", workdir=str(tmp_path))
    assert "output" in out1
    out2 = router.dispatch("write_stdin", session_id="s1", chars="ping\n")
    assert "ping" in out2["output"]
    # ensure cleanup
    router.pty_manager.close_all()
