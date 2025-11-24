from types import SimpleNamespace

from lincona.config import ApprovalPolicy, FsMode
from lincona.tools.fs import FsBoundary
from lincona.tools.router import ToolRouter


def test_router_registers_pty_with_shutdown(tmp_path):
    boundary = FsBoundary(FsMode.RESTRICTED, root=tmp_path)
    seen = SimpleNamespace(count=0)

    class DummyShutdown:
        def register_pty_manager(self, mgr):
            seen.count += 1

    ToolRouter(boundary, ApprovalPolicy.NEVER, shutdown_manager=DummyShutdown())
    assert seen.count == 1
