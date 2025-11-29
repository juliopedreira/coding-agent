import pathlib
import shutil
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from lincona.config import FsMode
from lincona.sessions import Event
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


@pytest.fixture
def capture_print(monkeypatch: pytest.MonkeyPatch):
    """Capture built-in print output into a list of strings."""

    calls: list[str] = []

    def fake_print(*args, **kwargs):
        calls.append(" ".join(str(a) for a in args))

    monkeypatch.setattr("builtins.print", fake_print)
    return calls


class FakeJsonlEventWriter:
    """Lightweight in-memory fake for JsonlEventWriter."""

    def __init__(self, path: pathlib.Path | str, *, fsync_every: int | None = None) -> None:
        self.path = pathlib.Path(path)
        self.events: list[Event] = []
        self._closed = False

    def append(self, event: Event) -> None:
        """Append event to in-memory list."""
        if not self._closed:
            self.events.append(event)

    def close(self) -> None:
        """Mark as closed."""
        self._closed = True

    def sync(self) -> None:
        """No-op for fake."""
        pass

    def __enter__(self) -> "FakeJsonlEventWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class FakeLogger:
    """Lightweight in-memory fake logger that records calls."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.info_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.debug_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.warning_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.error_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def info(self, *args: Any, **kwargs: Any) -> None:
        self.info_calls.append((args, kwargs))

    def debug(self, *args: Any, **kwargs: Any) -> None:
        self.debug_calls.append((args, kwargs))

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append((args, kwargs))

    def error(self, *args: Any, **kwargs: Any) -> None:
        self.error_calls.append((args, kwargs))


class FakeToolRouter:
    """Lightweight fake ToolRouter that records dispatch calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept same signature as ToolRouter but ignore arguments."""
        self.dispatch_calls: list[tuple[str, dict[str, Any]]] = []
        self._dispatch_return: Any = {"ok": True}

    def dispatch(self, name: str, **kwargs: Any) -> Any:
        """Record dispatch call and return configured result."""
        self.dispatch_calls.append((name, kwargs))
        return self._dispatch_return

    def set_dispatch_return(self, value: Any) -> None:
        """Configure return value for dispatch calls."""
        self._dispatch_return = value


@pytest.fixture
def fake_jsonl_writer() -> type[FakeJsonlEventWriter]:
    """Provide FakeJsonlEventWriter class for use in patches."""
    return FakeJsonlEventWriter


@pytest.fixture
def fake_logger() -> type[FakeLogger]:
    """Provide FakeLogger class for use in patches."""
    return FakeLogger


@pytest.fixture
def fake_tool_router() -> type[FakeToolRouter]:
    """Provide FakeToolRouter class for use in patches."""
    return FakeToolRouter


@pytest.fixture
def no_session_io(mocker):
    """Disable session file and logger side effects using mocker with autospec."""

    mocker.patch(
        "lincona.sessions.JsonlEventWriter",
        autospec=True,
        side_effect=lambda path, fsync_every=None: FakeJsonlEventWriter(path, fsync_every=fsync_every),
    )
    mocker.patch(
        "lincona.logging.configure_session_logger",
        autospec=True,
        side_effect=lambda *a, **k: FakeLogger("test"),
    )


# ============================================================================
# HTTP Transport Fixtures
# ============================================================================


class SequenceTransport:
    """Yield predefined chunk sequences per stream_response call."""

    def __init__(self, sequences):
        self.sequences = list(sequences)

    async def stream_response(self, payload):  # type: ignore[override]
        if not self.sequences:
            raise RuntimeError("no more streams")
        stream = self.sequences.pop(0)

        async def gen():
            for chunk in stream:
                yield chunk

        return gen()


class CapturingTransport:
    """Transport that captures the last payload and yields predefined chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.last_payload: Mapping[str, Any] | None = None

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        self.last_payload = payload
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def sequence_transport():
    """Factory fixture for SequenceTransport that yields predefined chunk sequences."""
    return SequenceTransport


@pytest.fixture
def capturing_transport():
    """Factory fixture for CapturingTransport that captures payloads and yields chunks."""
    return CapturingTransport


@pytest.fixture
def mock_http_handler():
    """Factory fixture for creating httpx request handlers with custom responses."""

    def _handler(
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
        record_request: dict[str, Any] | None = None,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            if record_request is not None:
                record_request["headers"] = dict(request.headers)
                record_request["url"] = str(request.url)
            return httpx.Response(status_code, text=text, headers=headers or {}, request=request)

        return handler

    return _handler


@pytest.fixture
def successful_response_handler(mock_http_handler):
    """Fixture factory for successful HTTP 200 responses with optional body and headers."""

    def _handler(body: str = "data: [DONE]\n", headers: dict[str, str] | None = None):
        return mock_http_handler(status_code=200, text=body, headers=headers)

    return _handler


@pytest.fixture
def error_response_handler(mock_http_handler):
    """Fixture factory for error HTTP responses (429, 500, etc.)."""

    def _handler(
        status_code: int,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        return mock_http_handler(status_code=status_code, text=text, headers=headers)

    return _handler


@pytest.fixture
def mock_http_client(mock_http_handler):
    """Fixture factory that provides an httpx.AsyncClient with MockTransport."""

    def _client(handler=None):
        if handler is None:
            handler = mock_http_handler()
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return _client


# ============================================================================
# Common Mock Patch Fixtures
# ============================================================================


@pytest.fixture
def mock_print(mocker):
    """Fixture that mocks builtins.print and returns a mock object with call tracking."""

    return mocker.patch("builtins.print", autospec=True)


@pytest.fixture
def mock_lincona_home(mocker, tmp_path: Path):
    """Fixture that patches os.environ['LINCONA_HOME'] to a temporary path."""

    home_path = tmp_path / "home"
    home_path.mkdir(parents=True, exist_ok=True)
    mocker.patch.dict("os.environ", {"LINCONA_HOME": str(home_path)})
    return home_path


@pytest.fixture
def mock_openai_client(mocker):
    """Fixture factory for mocking OpenAI client with fake models."""

    def _client(models_data: list[str] | None = None):
        class FakeModel:
            def __init__(self, id: str):
                self.id = id

        class FakeModels:
            def __init__(self, models_data: list[str] | None):
                self._models_data = models_data or []

            def list(self):
                class Obj:
                    data = [FakeModel(id) for id in self._models_data]

                return Obj()

        class FakeClient:
            def __init__(self, api_key: str | None = None, models_data: list[str] | None = None):
                self.models = FakeModels(models_data)

        return FakeClient

    return _client


# ============================================================================
# Error Transport Fixtures
# ============================================================================


class ErrorTransport:
    """Transport that raises a specific error when stream_response is called."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        raise self.error


@pytest.fixture
def error_transport_factory():
    """Factory fixture for transports that raise specific errors (timeout, request error, API errors)."""

    def _factory(error: Exception):
        return ErrorTransport(error)

    return _factory


class BadJsonTransport:
    """Transport that yields malformed JSON."""

    def __init__(self, bad_chunk: str) -> None:
        self.bad_chunk = bad_chunk

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        yield self.bad_chunk


@pytest.fixture
def bad_json_transport_factory():
    """Factory fixture for transports with malformed JSON."""

    def _factory(bad_chunk: str = "data: {not-json"):
        return BadJsonTransport(bad_chunk)

    return _factory


class GatedTransport:
    """Transport for backpressure testing that gates on an asyncio.Event."""

    def __init__(self, gate: Any, chunks: list[str]) -> None:
        self.gate = gate
        self.chunks = chunks
        self.started = False

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        self.started = True
        yield self.chunks[0]
        await self.gate.wait()
        for chunk in self.chunks[1:]:
            yield chunk


@pytest.fixture
def gated_transport_factory():
    """Factory fixture for backpressure testing transports."""

    def _factory(gate: Any, chunks: list[str]):
        return GatedTransport(gate, chunks)

    return _factory


# ============================================================================
# Client Fixtures
# ============================================================================


class DummyClient:
    """Dummy client that yields predefined events."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self._used = False

    async def submit(self, request: Any) -> AsyncIterator[Any]:
        if self._used:
            from lincona.openai_client.types import MessageDone

            yield MessageDone(finish_reason=None)
            return
        self._used = True
        for event in self._events:
            yield event


@pytest.fixture
def dummy_client_factory():
    """Factory fixture for creating DummyClient instances with predefined events."""

    def _factory(events: list[Any]):
        return DummyClient(events)

    return _factory


class BadClient:
    """Client that raises errors when methods are called."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("oops")

    class models:
        @staticmethod
        def list():
            raise RuntimeError("oops")


@pytest.fixture
def bad_client_factory():
    """Factory fixture for error-throwing clients."""

    def _factory(error: Exception | None = None):
        return BadClient(error)

    return _factory


@pytest.fixture
def mock_tool_router_factory(fake_tool_router):
    """Factory fixture for creating mock ToolRouter instances."""

    def _factory(dispatch_return: Any | None = None):
        if dispatch_return is None:
            dispatch_return = {"ok": True}
        router_instance = fake_tool_router()
        router_instance.set_dispatch_return(dispatch_return)
        return router_instance

    return _factory


# ============================================================================
# Common Patch Fixtures
# ============================================================================


@pytest.fixture
def mock_tool_router_patch(mocker, fake_tool_router):
    """Fixture that patches ToolRouter globally and returns the mock instance."""

    router_instance = fake_tool_router()
    mocker.patch("lincona.cli.ToolRouter", autospec=True, return_value=router_instance)
    return router_instance


@pytest.fixture
def mock_openai_patch(mocker, mock_openai_client):
    """Fixture that patches OpenAI client globally."""

    def _patch(models_data: list[str] | None = None):
        FakeClient = mock_openai_client(models_data=models_data)
        return mocker.patch("lincona.cli.OpenAI", autospec=True, return_value=FakeClient(models_data=models_data))

    return _patch
