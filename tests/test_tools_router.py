import pytest
import lincona.tools.router as router_module
from types import SimpleNamespace

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.approval import ApprovalRequiredError
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter, tool_specs
from lincona.tools.list_dir import ListDirInput
from lincona.tools.read_file import ReadFileInput
from lincona.tools.grep_files import GrepFilesInput
from lincona.tools.apply_patch import ApplyPatchInput
from lincona.tools.shell import ShellInput
from lincona.tools.exec_pty import ExecCommandInput, WriteStdinInput, PtyManager


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


def test_router_registers_shutdown_manager(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    called = {}

    class Shutdown:
        def register_pty_manager(self, mgr):
            called["mgr"] = mgr

    ToolRouter(boundary, ApprovalPolicy.NEVER, shutdown_manager=Shutdown())
    assert "mgr" in called


def test_router_registers_shutdown_manager_non_callable(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    class Shutdown:
        register_pty_manager = None

    # should not raise even if attribute is non-callable
    ToolRouter(boundary, ApprovalPolicy.NEVER, shutdown_manager=Shutdown())


def test_router_logs_requests_and_responses(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)

    class Logger:
        def __init__(self):
            self.logged = {"info": [], "debug": []}

        def info(self, msg, *args):
            self.logged["info"].append(msg % args)

        def debug(self, msg, *args):
            self.logged["debug"].append(msg % args)

    logger = Logger()
    router = ToolRouter(boundary, ApprovalPolicy.NEVER, logger=logger)
    router.dispatch("list_dir", path=".", depth=0)
    assert logger.logged["info"] and logger.logged["debug"]


def test_stringify_truncates_long_payload():
    long_text = "x" * 2500
    result = ToolRouter._stringify({"a": long_text})
    assert result.endswith("[truncated]")


def test_stringify_repr_fallback():
    class Bad:
        def __str__(self):
            raise TypeError("no str")

    result = ToolRouter._stringify({"a": {1, 2}})  # set not JSON-serializable
    assert "[1, 2]" not in result or result.startswith("{")
    assert "Bad" in ToolRouter._stringify(Bad())


def test_inline_schema_allof_resolution():
    schema = {
        "$defs": {"Inner": {"properties": {"x": {"type": "string"}}}},
        "allOf": [{"$ref": "#/$defs/Inner"}],
    }
    resolved = router_module._inline_schema(schema)
    assert "properties" in resolved and "x" in resolved["properties"]


def test_inline_schema_passthrough():
    schema = {"properties": {"x": {"type": "string"}}}
    assert router_module._inline_schema(schema) == schema


def test_inline_schema_no_matching_ref_returns_schema():
    schema = {"$defs": {"Inner": {"properties": {"x": {"type": "string"}}}}, "allOf": [{"$ref": "#/$defs/Other"}]}
    assert router_module._inline_schema(schema) == schema


def test_schema_for_model_flattens_allof():
    class Dummy:
        @staticmethod
        def model_json_schema():
            return {
                "$defs": {"Inner": {"properties": {"x": {"type": "string"}}}},
                "allOf": [{"$ref": "#/$defs/Inner"}],
            }

    schema = router_module._schema_for_model(Dummy)
    assert schema["required"] == ["x"]


def test_inline_schema_loop_multiple_items():
    schema = {
        "$defs": {"A": {"properties": {"a": {"type": "string"}}}, "B": {"properties": {"b": {"type": "string"}}}},
        "allOf": [{"$ref": "#/$defs/Unknown"}, {"$ref": "#/$defs/B"}],
    }
    resolved = router_module._inline_schema(schema)
    assert resolved["properties"]["b"]["type"] == "string"


def test_inline_schema_condition_false_returns_schema():
    schema = {"$defs": None, "allOf": None}
    assert router_module._inline_schema(schema) == schema


def test_inline_schema_skips_items_without_ref():
    schema = {
        "$defs": {"B": {"properties": {"b": {"type": "string"}}}},
        "allOf": [{"notref": "noop"}, {"$ref": "#/$defs/B"}],
    }
    resolved = router_module._inline_schema(schema)
    assert "b" in resolved.get("properties", {})


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


def test_router_registers_pty_with_shutdown(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    seen = SimpleNamespace(count=0)

    class DummyShutdown:
        def register_pty_manager(self, mgr):
            seen.count += 1

    ToolRouter(boundary, ApprovalPolicy.NEVER, shutdown_manager=DummyShutdown())
    assert seen.count == 1


@pytest.mark.parametrize(
    "model",
    [ListDirInput, ReadFileInput, GrepFilesInput, ApplyPatchInput, ShellInput, ExecCommandInput, WriteStdinInput],
)
def test_schema_required_matches_properties(model):
    schema = router_module._schema_for_model(model)
    props = schema.get("properties", {}) or {}
    assert set(schema.get("required", [])) == set(props.keys())


@pytest.mark.parametrize(
    "model",
    [ListDirInput, ReadFileInput, GrepFilesInput, ApplyPatchInput, ShellInput, ExecCommandInput, WriteStdinInput],
)
def test_schema_no_path_format(model):
    schema = router_module._schema_for_model(model)
    props = schema.get("properties", {}) or {}
    for definition in props.values():
        fmt = definition.get("format")
        assert fmt not in {"path", "Path"}


def test_tool_specs_all_functions(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    specs = tool_specs(boundary, PtyManager(boundary))
    names = {spec["function"]["name"] for spec in specs if "function" in spec}
    expected = {
        "list_dir",
        "read_file",
        "grep_files",
        "apply_patch_json",
        "apply_patch_freeform",
        "shell",
        "exec_command",
        "write_stdin",
    }
    assert expected.issubset(names)


def _make_router(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    return ToolRouter(boundary, ApprovalPolicy.NEVER)


def test_router_list_dir_and_read_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")

    router = _make_router(tmp_path)
    entries = router.dispatch("list_dir", path=".", depth=1)
    assert "file.txt" in entries

    text, truncated = router.dispatch("read_file", path="file.txt", offset=0, limit=10, mode="slice", indent="    ")
    assert "hello" in text
    assert truncated is False


def test_router_grep_files(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("todo: fix\n", encoding="utf-8")
    router = _make_router(tmp_path)

    results = router.dispatch("grep_files", pattern="todo", path=".", include=["*.txt"], limit=10)
    assert results
    assert results[0]["file"] == "a.txt"
    assert results[0]["matches"][0]["line_num"] == 1


def test_router_apply_patch_and_read_back(tmp_path):
    patch = """--- a/new.txt
+++ b/new.txt
@@ -0,0 +1,1 @@
+hi
"""
    router = _make_router(tmp_path)
    res = router.dispatch("apply_patch_json", patch=patch)
    assert any(entry.get("created") for entry in res)
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hi"


def test_router_shell_runs_command(tmp_path):
    router = _make_router(tmp_path)
    result = router.dispatch("shell", command="echo hi", workdir=str(tmp_path), timeout_ms=5000)
    assert result["stdout"].strip() == "hi"
    assert result["returncode"] == 0


def test_router_exec_and_write_stdin(tmp_path):
    router = _make_router(tmp_path)
    out1 = router.dispatch("exec_command", session_id="s1", cmd="cat", workdir=str(tmp_path))
    assert "output" in out1
    out2 = router.dispatch("write_stdin", session_id="s1", chars="ping\n")
    assert "ping" in out2["output"]
    router.pty_manager.close_all()
