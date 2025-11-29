import pathlib
import shutil
import sys

import pytest

from lincona.config import FsMode
from lincona.tools.fs import FsBoundary

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

# Ensure src/ is importable when running tests without installing the package.
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def _isolate_lincona_home(monkeypatch: pytest.MonkeyPatch):
    """Point LINCONA_HOME at a repo-local sandbox so we never touch the real FS."""

    home = PROJECT_ROOT / ".work"
    if home.exists():
        shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LINCONA_HOME", str(home))
    yield


@pytest.fixture
def restricted_boundary(tmp_path: pathlib.Path) -> FsBoundary:
    """Shared restricted FsBoundary rooted in a temporary sandbox."""

    return FsBoundary(FsMode.RESTRICTED, root=tmp_path)


@pytest.fixture
def dummy_tool_classes():
    """Provide simple Tool/Registration-friendly classes for reuse."""

    from lincona.tools.base import Tool, ToolRequest, ToolResponse

    class EchoRequest(ToolRequest):
        msg: str

    class EchoResponse(ToolResponse):
        msg: str

    class EchoTool(Tool[EchoRequest, EchoResponse]):
        name = "echo"
        description = "echo upper"
        InputModel = EchoRequest
        OutputModel = EchoResponse

        def execute(self, request: EchoRequest) -> EchoResponse:  # type: ignore[override]
            return EchoResponse(msg=request.msg.upper())

    return EchoRequest, EchoResponse, EchoTool
