import pytest

import lincona.tools.router as router_module
from lincona.config import ApprovalPolicy
from lincona.tools.apply_patch import ApplyPatchInput, ApplyPatchOutput, PatchResultModel
from lincona.tools.approval import ApprovalRequiredError
from lincona.tools.exec_pty import ExecCommandInput, ExecCommandOutput, PtyManager, WriteStdinInput, WriteStdinOutput
from lincona.tools.grep_files import FileMatches, GrepFilesInput, GrepFilesOutput, LineMatch
from lincona.tools.list_dir import ListDirInput, ListDirOutput
from lincona.tools.read_file import ReadFileInput, ReadFileOutput
from lincona.tools.registry import ToolRegistration
from lincona.tools.router import ToolRouter, tool_specs
from lincona.tools.shell import ShellInput, ShellOutput


@pytest.fixture(autouse=True)
def stub_tool_registrations(monkeypatch: pytest.MonkeyPatch):
    """Stub tool registrations to avoid real filesystem/process work."""

    def _registrations(boundary, pty_manager=None):
        return [
            ToolRegistration(
                name="list_dir",
                description="",
                input_model=ListDirInput,
                output_model=ListDirOutput,
                handler=lambda req: ListDirOutput(entries=["a/", "file.txt"]),
                result_adapter=lambda out: out.entries,
                end_event_builder=lambda req, out: {"count": len(out.entries)},
            ),
            ToolRegistration(
                name="read_file",
                description="",
                input_model=ReadFileInput,
                output_model=ReadFileOutput,
                handler=lambda req: ReadFileOutput(text="hello\nworld\n", truncated=False),
                result_adapter=lambda out: (out.text, out.truncated),
                end_event_builder=lambda req, out: {"truncated": out.truncated},
            ),
            ToolRegistration(
                name="grep_files",
                description="",
                input_model=GrepFilesInput,
                output_model=GrepFilesOutput,
                handler=lambda req: GrepFilesOutput(
                    results=[FileMatches(file="a.txt", matches=[LineMatch(line_num=1, line="todo", truncated=False)])]
                ),
                result_adapter=lambda out: [res.model_dump() for res in out.results],
                end_event_builder=lambda req, out: {"files": len(out.results)},
            ),
            ToolRegistration(
                name="apply_patch_json",
                description="",
                input_model=ApplyPatchInput,
                output_model=ApplyPatchOutput,
                handler=lambda req: ApplyPatchOutput(
                    results=[PatchResultModel(path="new.txt", bytes_written=2, created=True)]
                ),
                requires_approval=True,
                result_adapter=lambda out: [res.model_dump() for res in out.results],
                end_event_builder=lambda req, out: {"files": len(out.results)},
            ),
            ToolRegistration(
                name="apply_patch_freeform",
                description="",
                input_model=ApplyPatchInput,
                output_model=ApplyPatchOutput,
                handler=lambda req: ApplyPatchOutput(
                    results=[PatchResultModel(path="f.txt", bytes_written=1, created=False)]
                ),
                requires_approval=True,
                result_adapter=lambda out: [res.model_dump() for res in out.results],
                end_event_builder=lambda req, out: {"files": len(out.results)},
            ),
            ToolRegistration(
                name="shell",
                description="",
                input_model=ShellInput,
                output_model=ShellOutput,
                handler=lambda req: ShellOutput(
                    stdout="hi",
                    stderr="",
                    returncode=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    timeout=False,
                    message=None,
                ),
                requires_approval=True,
                result_adapter=lambda out: out.model_dump(),
                end_event_builder=lambda req, out: {"returncode": out.returncode, "timeout": out.timeout},
            ),
            ToolRegistration(
                name="exec_command",
                description="",
                input_model=ExecCommandInput,
                output_model=ExecCommandOutput,
                handler=lambda req: ExecCommandOutput(output="ok", truncated=False),
                requires_approval=True,
                result_adapter=lambda out: out.model_dump(),
                end_event_builder=lambda req, out: {
                    "session_id": req.session_id,
                    "truncated": out.truncated,
                    "returncode": None,
                },
            ),
            ToolRegistration(
                name="write_stdin",
                description="",
                input_model=WriteStdinInput,
                output_model=WriteStdinOutput,
                handler=lambda req: WriteStdinOutput(output="pong", truncated=False),
                requires_approval=True,
                result_adapter=lambda out: out.model_dump(),
                end_event_builder=lambda req, out: {
                    "session_id": req.session_id,
                    "truncated": out.truncated,
                    "returncode": None,
                },
            ),
        ]

    monkeypatch.setattr(router_module, "get_tool_registrations", _registrations)


def _make_router(boundary, approval=ApprovalPolicy.NEVER, **kwargs):
    return ToolRouter(boundary, approval, **kwargs)


def test_tool_specs_contains_tools():
    names = {spec["function"]["name"] for spec in tool_specs()}
    assert {"list_dir", "read_file", "grep_files", "apply_patch_freeform", "shell"}.issubset(names)


def test_dispatch_list_dir(restricted_boundary):
    router = _make_router(restricted_boundary)
    entries = router.dispatch("list_dir", path=".", depth=1)
    assert "file.txt" in entries


def test_dispatch_apply_patch_honors_approval(restricted_boundary):
    router = _make_router(restricted_boundary, ApprovalPolicy.ALWAYS)
    with pytest.raises(ApprovalRequiredError):
        router.dispatch("apply_patch_json", patch="ignored")


def test_dispatch_exec_command_uses_manager(restricted_boundary):
    router = _make_router(restricted_boundary)
    result = router.dispatch("exec_command", session_id="s1", cmd="echo hi", workdir=".")
    assert result["output"] == "ok"


def test_dispatch_shell_blocked_by_approval(restricted_boundary):
    router = _make_router(restricted_boundary, ApprovalPolicy.ALWAYS)
    with pytest.raises(ApprovalRequiredError):
        router.dispatch("shell", command="echo hi")


def test_dispatch_apply_patch_freeform(restricted_boundary):
    router = _make_router(restricted_boundary)
    res = router.dispatch("apply_patch_freeform", patch="ignored")
    assert res[0]["path"] == "f.txt"
    assert router.events[-1]["files"] == 1


def test_dispatch_apply_patch_json(restricted_boundary):
    router = _make_router(restricted_boundary)
    res = router.dispatch("apply_patch_json", patch="ignored")
    assert any(entry.get("created") for entry in res)
    assert router.events[-1]["files"] == 1


def test_dispatch_unknown_tool_raises(restricted_boundary):
    router = _make_router(restricted_boundary)
    with pytest.raises(ValueError):
        router.dispatch("unknown_tool")


def test_dispatch_write_stdin(restricted_boundary):
    router = _make_router(restricted_boundary)
    router.dispatch("exec_command", session_id="s2", cmd="cat")
    result = router.dispatch("write_stdin", session_id="s2", chars="ping\n")
    assert "pong" in result["output"]
    assert any(e for e in router.events if e["tool"] == "write_stdin" and e["phase"] == "end")


def test_router_registers_shutdown_manager(restricted_boundary):
    called = {}

    class Shutdown:
        def register_pty_manager(self, mgr):
            called["mgr"] = mgr

    _make_router(restricted_boundary, shutdown_manager=Shutdown())
    assert "mgr" in called


def test_router_registers_shutdown_manager_non_callable(restricted_boundary):
    class Shutdown:
        register_pty_manager = None

    _make_router(restricted_boundary, shutdown_manager=Shutdown())


def test_router_logs_requests_and_responses(restricted_boundary):
    class Logger:
        def __init__(self):
            self.logged = {"info": [], "debug": []}

        def info(self, msg, *args):
            self.logged["info"].append(msg % args)

        def debug(self, msg, *args):
            self.logged["debug"].append(msg % args)

    logger = Logger()
    router = _make_router(restricted_boundary, logger=logger)
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
    assert result.startswith("{")
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


def test_router_emits_start_and_end(restricted_boundary):
    router = _make_router(restricted_boundary)
    router.dispatch("list_dir", path=".", depth=1)
    assert router.events[0]["phase"] == "start"
    assert router.events[-1]["phase"] == "end"


def test_router_shell_end_event(restricted_boundary):
    router = _make_router(restricted_boundary)
    router.dispatch("shell", command="echo hi", workdir=".")
    assert any(e for e in router.events if e["tool"] == "shell" and e["phase"] == "end")


def test_router_approval_blocks_on_request(restricted_boundary):
    router = _make_router(restricted_boundary, ApprovalPolicy.ON_REQUEST)
    with pytest.raises(ApprovalRequiredError):
        router.dispatch("apply_patch_json", patch="ignored")


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


def test_tool_specs_all_functions(restricted_boundary):
    specs = tool_specs(restricted_boundary, PtyManager(restricted_boundary))
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


def test_router_list_dir_and_read_file(restricted_boundary):
    router = _make_router(restricted_boundary)
    entries = router.dispatch("list_dir", path=".", depth=1)
    assert "file.txt" in entries

    text, truncated = router.dispatch("read_file", path="file.txt", offset=0, limit=10, mode="slice", indent="    ")
    assert "hello" in text
    assert truncated is False


def test_router_grep_files(restricted_boundary):
    router = _make_router(restricted_boundary)
    results = router.dispatch("grep_files", pattern="todo", path=".", include=["*.txt"], limit=10)
    assert results[0]["file"] == "a.txt"
    assert results[0]["matches"][0]["line_num"] == 1


def test_router_apply_patch_and_read_back(restricted_boundary):
    router = _make_router(restricted_boundary)
    res = router.dispatch("apply_patch_json", patch="ignored")
    assert any(entry.get("created") for entry in res)
    assert router.events[-1]["files"] == 1


def test_router_shell_runs_command(restricted_boundary):
    router = _make_router(restricted_boundary)
    result = router.dispatch("shell", command="echo hi", workdir=".", timeout_ms=5000)
    assert result["stdout"] == "hi"
    assert result["returncode"] == 0


def test_router_exec_and_write_stdin(restricted_boundary):
    router = _make_router(restricted_boundary)
    out1 = router.dispatch("exec_command", session_id="s1", cmd="cat", workdir=".")
    assert out1["output"] == "ok"
    out2 = router.dispatch("write_stdin", session_id="s1", chars="ping\n")
    assert "pong" in out2["output"]
    router.pty_manager.close_all()
