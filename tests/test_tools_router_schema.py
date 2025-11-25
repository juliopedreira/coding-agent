from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.exec_pty import PtyManager
from lincona.tools.fs import FsBoundary
from lincona.tools.read_file import ReadFileInput
from lincona.tools.router import ToolRouter, _inline_schema, _schema_for_model


def test_schema_for_model_inlines_all_properties():
    schema = _schema_for_model(ReadFileInput)
    required = set(schema.get("required", []))
    assert {"path", "offset", "limit", "mode", "indent"} <= required
    assert schema.get("additionalProperties") is False


def test_inline_schema_falls_back():
    orig = {"properties": {"a": {"type": "string"}}}
    assert _inline_schema(orig) is orig


def test_inline_schema_unwraps_defs():
    schema = {
        "allOf": [{"$ref": "#/$defs/ReadFileInput"}],
        "$defs": {
            "ReadFileInput": {
                "type": "object",
                "properties": {"foo": {"type": "string"}},
            }
        },
    }
    inline = _inline_schema(schema)
    assert inline.get("properties", {}).get("foo") is not None


def test_tool_router_registers_shutdown(tmp_path):
    class Shutdown:
        def __init__(self):
            self.registered = None

        def register_pty_manager(self, mgr):
            self.registered = mgr

    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    shutdown = Shutdown()
    router = ToolRouter(boundary, ApprovalPolicy.NEVER, pty_manager=PtyManager(boundary), shutdown_manager=shutdown)
    assert shutdown.registered is router.pty_manager
