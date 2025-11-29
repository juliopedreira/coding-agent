import pathlib
import shutil
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from lincona.config import ApprovalPolicy, FsMode, LogLevel, ModelCapabilities, ReasoningEffort, Settings, Verbosity
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


@pytest.fixture(scope="session")
def fake_jsonl_writer() -> type[FakeJsonlEventWriter]:
    """Provide FakeJsonlEventWriter class for use in patches (session-scoped for speed)."""
    return FakeJsonlEventWriter


@pytest.fixture(scope="session")
def fake_logger() -> type[FakeLogger]:
    """Provide FakeLogger class for use in patches (session-scoped for speed)."""
    return FakeLogger


@pytest.fixture(scope="session")
def fake_tool_router() -> type[FakeToolRouter]:
    """Provide FakeToolRouter class for use in patches (session-scoped for speed)."""
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


@pytest.fixture(scope="session")
def sequence_transport():
    """Factory fixture for SequenceTransport that yields predefined chunk sequences (session-scoped for speed)."""
    return SequenceTransport


@pytest.fixture(scope="session")
def capturing_transport():
    """Factory fixture for CapturingTransport that captures payloads and yields chunks (session-scoped for speed)."""
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
def mock_subprocess_run(mocker):
    """Fixture factory for mocking subprocess.run with customizable behavior.

    Returns a function that creates a mock for subprocess.run. The mock can be
    customized by passing parameters or by modifying the returned mock object.
    """

    def _factory(
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timeout_exception: Exception | None = None,
        side_effect=None,
    ):
        """Create a mock for subprocess.run.

        Args:
            stdout: Standard output to return (if side_effect not provided)
            stderr: Standard error to return (if side_effect not provided)
            returncode: Exit code to return (if side_effect not provided)
            timeout_exception: Exception to raise (e.g., subprocess.TimeoutExpired)
            side_effect: Custom side effect function (takes precedence)
        """
        from types import SimpleNamespace

        if side_effect is not None:
            return mocker.patch("subprocess.run", autospec=True, side_effect=side_effect)

        def fake_run(command, **kwargs):
            if timeout_exception:
                raise timeout_exception
            return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

        return mocker.patch("subprocess.run", autospec=True, side_effect=fake_run)

    return _factory


@pytest.fixture
def mock_path_methods(mocker):
    """Fixture factory for mocking Path methods with customizable behavior."""

    def _factory(
        exists: bool | None = None,
        read_text: str | None = None,
        iterdir: list[Path] | None = None,
        is_file: bool | None = None,
        is_symlink: bool | None = None,
        side_effect_exists: Any | None = None,
        side_effect_read_text: Any | None = None,
        side_effect_iterdir: Any | None = None,
    ):
        """Create mocks for common Path methods.

        Args:
            exists: Return value for Path.exists()
            read_text: Return value for Path.read_text()
            iterdir: Return value for Path.iterdir()
            is_file: Return value for Path.is_file()
            is_symlink: Return value for Path.is_symlink()
            side_effect_exists: Side effect function for Path.exists()
            side_effect_read_text: Side effect function for Path.read_text()
            side_effect_iterdir: Side effect function for Path.iterdir()
        """
        patches = {}

        if exists is not None or side_effect_exists is not None:
            kwargs = {"autospec": True}
            if side_effect_exists is not None:
                kwargs["side_effect"] = side_effect_exists
            else:
                kwargs["return_value"] = exists
            patches["exists"] = mocker.patch.object(Path, "exists", **kwargs)

        if read_text is not None or side_effect_read_text is not None:
            kwargs = {"autospec": True}
            if side_effect_read_text is not None:
                kwargs["side_effect"] = side_effect_read_text
            else:
                kwargs["return_value"] = read_text
            patches["read_text"] = mocker.patch.object(Path, "read_text", **kwargs)

        if iterdir is not None or side_effect_iterdir is not None:
            kwargs = {"autospec": True}
            if side_effect_iterdir is not None:
                kwargs["side_effect"] = side_effect_iterdir
            else:
                kwargs["return_value"] = iterdir
            patches["iterdir"] = mocker.patch.object(Path, "iterdir", **kwargs)

        if is_file is not None:
            patches["is_file"] = mocker.patch.object(Path, "is_file", autospec=True, return_value=is_file)

        if is_symlink is not None:
            patches["is_symlink"] = mocker.patch.object(Path, "is_symlink", autospec=True, return_value=is_symlink)

        return patches

    return _factory


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


@pytest.fixture(scope="session")
def error_transport_factory():
    """Factory fixture for transports that raise specific errors (timeout, request error, API errors).

    Session-scoped for speed.
    """

    def _factory(error: Exception):
        return ErrorTransport(error)

    return _factory


class BadJsonTransport:
    """Transport that yields malformed JSON."""

    def __init__(self, bad_chunk: str) -> None:
        self.bad_chunk = bad_chunk

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        yield self.bad_chunk


@pytest.fixture(scope="session")
def bad_json_transport_factory():
    """Factory fixture for transports with malformed JSON (session-scoped for speed)."""

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


@pytest.fixture(scope="session")
def gated_transport_factory():
    """Factory fixture for backpressure testing transports (session-scoped for speed)."""

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


@pytest.fixture(scope="session")
def dummy_client_factory():
    """Factory fixture for creating DummyClient instances with predefined events (session-scoped for speed)."""

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


@pytest.fixture(scope="session")
def bad_client_factory():
    """Factory fixture for error-throwing clients (session-scoped for speed)."""

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


# ============================================================================
# Enhanced Transport Fixtures for MockResponsesTransport
# ============================================================================


@pytest.fixture(scope="session")
def mock_responses_transport():
    """Factory fixture for creating MockResponsesTransport instances with common configurations.

    Session-scoped for speed.
    """

    def _factory(
        chunks: list[str | bytes] | None = None,
        status_code: int | None = None,
        logger: Any | None = None,
    ):
        """Create a MockResponsesTransport instance.

        Args:
            chunks: List of chunks to yield (default: ["data: [DONE]\n"])
            status_code: HTTP status code to raise (default: None, no error)
            logger: Optional logger function
        """
        from lincona.openai_client.transport import MockResponsesTransport

        if chunks is None:
            chunks = ["data: [DONE]\n"]
        if status_code is not None:
            return MockResponsesTransport(chunks, status_code=status_code, logger=logger)
        else:
            return MockResponsesTransport(chunks, logger=logger)

    return _factory


@pytest.fixture
def mock_transport_success(mock_responses_transport):
    """Fixture factory for successful transport responses."""

    def _factory(chunks: list[str] | None = None):
        if chunks is None:
            chunks = ["data: [DONE]\n"]
        return mock_responses_transport(chunks=chunks)

    return _factory


@pytest.fixture
def mock_transport_error(mock_responses_transport):
    """Fixture factory for error transport responses."""

    def _factory(status_code: int, chunks: list[str] | None = None):
        return mock_responses_transport(chunks=chunks or [], status_code=status_code)

    return _factory


@pytest.fixture
def success_transport(mock_responses_transport):
    """Preset transport that yields [DONE] immediately (most common success case)."""
    return mock_responses_transport(chunks=["data: [DONE]\n"])


@pytest.fixture
def text_delta_transport(mock_responses_transport):
    """Preset transport with text delta chunks followed by [DONE]."""
    return mock_responses_transport(
        chunks=[
            'data: {"type":"text_delta","delta":{"text":"hello"}}\n',
            "data: [DONE]\n",
        ]
    )


@pytest.fixture
def tool_call_transport(mock_responses_transport):
    """Preset transport with tool call sequence followed by [DONE]."""
    return mock_responses_transport(
        chunks=[
            'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"list_dir","arguments":""}}\n',
            'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"{\\"path\\": \\".\\"}"}}\n',
            (
                'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"list_dir",'
                '"arguments":"{\\"path\\": \\".\\"}"}}\n'
            ),
            "data: [DONE]\n",
        ]
    )


@pytest.fixture
def empty_transport(mock_responses_transport):
    """Preset transport that yields nothing (for error cases or empty responses)."""
    return mock_responses_transport(chunks=[])


@pytest.fixture
def single_chunk_transport(mock_responses_transport):
    """Factory fixture for creating transports with a single chunk."""

    def _factory(chunk: str | bytes) -> Any:
        """Create transport with single chunk.

        Args:
            chunk: Single chunk to yield

        Returns:
            Transport instance yielding the single chunk
        """
        return mock_responses_transport(chunks=[chunk])

    return _factory


# ============================================================================
# Common Path Mock Presets
# ============================================================================


@pytest.fixture
def mock_path_exists_file(mock_path_methods):
    """Fixture that mocks Path.exists() to return True and Path.is_file() to return True."""

    def _factory(path: Path | None = None):
        if path is not None:
            patches = mock_path_methods(
                side_effect_exists=lambda self: True if self == path else Path.exists(self),
                is_file=True,
            )
        else:
            patches = mock_path_methods(exists=True, is_file=True)
        return patches

    return _factory


@pytest.fixture
def mock_path_read_text(mock_path_methods):
    """Fixture that mocks Path.read_text() with a given value."""

    def _factory(text: str, path: Path | None = None):
        if path is not None:
            patches = mock_path_methods(
                side_effect_read_text=lambda self: text if self == path else Path.read_text(self)
            )
        else:
            patches = mock_path_methods(read_text=text)
        return patches

    return _factory


@pytest.fixture
def mock_path_iterdir(mock_path_methods):
    """Fixture that mocks Path.iterdir() with a given list of paths."""

    def _factory(paths: list[Path], path: Path | None = None):
        if path is not None:
            patches = mock_path_methods(
                side_effect_iterdir=lambda self: iter(paths) if self == path else Path.iterdir(self)
            )
        else:
            patches = mock_path_methods(iterdir=paths)
        return patches

    return _factory


# ============================================================================
# Common Settings Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def default_settings() -> Settings:
    """Session-scoped default Settings for tests with standard configuration."""
    models = {
        "gpt-5.1-codex-mini": ModelCapabilities(
            reasoning_effort=(
                ReasoningEffort.NONE,
                ReasoningEffort.MINIMAL,
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
            ),
            default_reasoning=ReasoningEffort.MINIMAL,
            verbosity=(Verbosity.LOW, Verbosity.MEDIUM, Verbosity.HIGH),
            default_verbosity=Verbosity.MEDIUM,
        )
    }
    return Settings(
        api_key="test",
        model="gpt-5.1-codex-mini",
        reasoning_effort=ReasoningEffort.MINIMAL,
        verbosity=Verbosity.MEDIUM,
        models=models,
        fs_mode=FsMode.UNRESTRICTED,
        approval_policy=ApprovalPolicy.NEVER,
        log_level=LogLevel.ERROR,
    )


@pytest.fixture
def restricted_settings(default_settings: Settings) -> Settings:
    """Settings with RESTRICTED fs_mode for tests requiring restricted filesystem."""
    return Settings(**{**default_settings.model_dump(), "fs_mode": FsMode.RESTRICTED})


@pytest.fixture
def unrestricted_settings(default_settings: Settings) -> Settings:
    """Settings with UNRESTRICTED fs_mode (same as default, but explicit)."""
    return Settings(**{**default_settings.model_dump(), "fs_mode": FsMode.UNRESTRICTED})


@pytest.fixture
def settings_factory(default_settings: Settings):
    """Factory fixture for creating custom Settings with overrides."""

    def _factory(**overrides) -> Settings:
        """Create Settings with custom overrides.

        Args:
            **overrides: Settings fields to override

        Returns:
            New Settings instance with overrides applied
        """
        return Settings(**{**default_settings.model_dump(), **overrides})

    return _factory


# ============================================================================
# ConversationRequest Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def simple_conversation_request():
    """Session-scoped fixture for a simple ConversationRequest (reusable for speed)."""
    from lincona.openai_client.types import ConversationRequest, Message, MessageRole

    return ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-4.1",
    )


@pytest.fixture
def conversation_request_factory():
    """Factory fixture for creating customizable ConversationRequest instances."""

    def _factory(**overrides):
        from lincona.openai_client.types import ConversationRequest, Message, MessageRole

        defaults = {
            "messages": [Message(role=MessageRole.USER, content="hi")],
            "model": "gpt-4.1",
        }
        defaults.update(overrides)
        return ConversationRequest(**defaults)

    return _factory


# ============================================================================
# Fake Transport Classes (Session-Scoped for Speed)
# ============================================================================


class FakeStreamCtx:
    """Fake stream context for HTTP transport tests (session-scoped)."""

    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {"x-request-id": "req-1"}
        self._chunks = chunks or ['data: {"delta":"hi"}', "data: [DONE]"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aiter_lines(self):
        for chunk in self._chunks:
            yield chunk

    def raise_for_status(self):
        return None


class FakeHttpClient:
    """Fake HTTP client that records calls and returns FakeStreamCtx (session-scoped)."""

    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self._recorded: dict[str, Any] = {}

    def stream(self, method, url, json=None, headers=None, timeout=None):
        lowered = {k.lower(): v for k, v in (headers or {}).items()}
        self._recorded.update(method=method, url=url, payload=json, headers=lowered)
        return FakeStreamCtx()

    async def aclose(self):
        return None

    @property
    def recorded(self):
        """Get recorded request data."""
        return self._recorded


@pytest.fixture(scope="session")
def fake_stream_ctx_factory():
    """Factory fixture for creating FakeStreamCtx instances (session-scoped for speed)."""
    return FakeStreamCtx


@pytest.fixture(scope="session")
def fake_http_client_factory():
    """Factory fixture for creating FakeHttpClient instances (session-scoped for speed)."""
    return FakeHttpClient


class FakeSDKResponses:
    """Fake SDK responses client for OpenAISDKResponsesTransport tests."""

    def __init__(self, evts):
        self._events = evts

    async def create(self, **kwargs):
        async def gen():
            for e in self._events:
                yield e

        return gen()


class FakeSDKClient:
    """Fake SDK client for OpenAISDKResponsesTransport tests."""

    def __init__(self, evts):
        self.responses = FakeSDKResponses(evts)


@pytest.fixture(scope="session")
def fake_sdk_client_factory():
    """Factory fixture for creating FakeSDKClient instances (session-scoped for speed)."""
    return FakeSDKClient


# ============================================================================
# Patch Pattern Fixtures
# ============================================================================


@pytest.fixture
def mock_parse_unified_diff(mocker):
    """Factory fixture for mocking parse_unified_diff with common patterns."""

    def _factory(return_value=None, side_effect=None):
        import lincona.tools.apply_patch as apply_patch_mod

        if side_effect is not None:
            return mocker.patch.object(apply_patch_mod, "parse_unified_diff", autospec=True, side_effect=side_effect)
        return mocker.patch.object(
            apply_patch_mod, "parse_unified_diff", autospec=True, return_value=return_value or []
        )

    return _factory


@pytest.fixture
def mock_path_replace(mocker):
    """Factory fixture for mocking Path.replace with common patterns."""

    def _factory(side_effect=None, return_value=None):
        if side_effect is not None:
            return mocker.patch.object(Path, "replace", autospec=True, side_effect=side_effect)
        return mocker.patch.object(Path, "replace", autospec=True, return_value=return_value)

    return _factory


@pytest.fixture
def mock_named_temporary_file(mocker):
    """Factory fixture for mocking tempfile.NamedTemporaryFile with customizable behavior.

    Returns a function that creates a mock for tempfile.NamedTemporaryFile. The mock can be
    customized by passing a side_effect function or by using the default behavior that wraps
    the real NamedTemporaryFile.
    """

    def _factory(side_effect=None, module=None):
        """Create a mock for tempfile.NamedTemporaryFile.

        Args:
            side_effect: Custom side effect function (if None, wraps real NamedTemporaryFile)
            module: Module object to patch (default: tempfile, but can be module-specific like apply_patch_mod.tempfile)

        Returns:
            Mock object for NamedTemporaryFile
        """
        import tempfile

        if module is None:
            module = tempfile

        if side_effect is not None:
            return mocker.patch.object(module, "NamedTemporaryFile", autospec=True, side_effect=side_effect)

        # Default: wrap real NamedTemporaryFile to allow tracking
        real_namedtemp = tempfile.NamedTemporaryFile

        def fake_namedtemp(*args, **kwargs):
            return real_namedtemp(*args, **kwargs)

        return mocker.patch.object(module, "NamedTemporaryFile", autospec=True, side_effect=fake_namedtemp)

    return _factory


@pytest.fixture
def httpx_response_factory():
    """Factory fixture for creating httpx.Response objects with common configurations.

    Returns a function that creates httpx.Response objects with customizable status codes,
    headers, and request objects.
    """

    def _factory(
        status_code: int,
        request: httpx.Request | None = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> httpx.Response:
        """Create an httpx.Response object.

        Args:
            status_code: HTTP status code
            request: Optional httpx.Request object (default: creates a dummy POST request)
            headers: Optional response headers
            text: Optional response body text

        Returns:
            httpx.Response object
        """
        if request is None:
            request = httpx.Request("POST", "https://example.com")
        return httpx.Response(status_code, request=request, headers=headers or {}, text=text)

    return _factory


# ============================================================================
# Consolidated CLI Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_cli_session_mocks(mocker, fake_jsonl_writer, fake_logger):
    """Fixture that patches common CLI session-related mocks in one go."""

    mocker.patch(
        "lincona.cli.get_lincona_home",
        autospec=True,
        return_value=Path("/virtual/home"),
    )
    mocker.patch(
        "lincona.sessions.JsonlEventWriter",
        autospec=True,
        side_effect=lambda path, fsync_every=None: fake_jsonl_writer(path, fsync_every=fsync_every),
    )
    mocker.patch(
        "lincona.logging.configure_session_logger",
        autospec=True,
        side_effect=lambda *a, **k: fake_logger("test"),
    )


@pytest.fixture
def mock_cli_path_methods(mocker):
    """Fixture that patches common Path methods used in CLI tests."""

    def _factory(
        exists: bool | Any = True,
        read_text: str | Any = '{"hello":true}',
    ):
        """Create mocks for Path.exists() and Path.read_text().

        Args:
            exists: Return value or side_effect for Path.exists()
            read_text: Return value or side_effect for Path.read_text()
        """
        if callable(exists):
            mocker.patch.object(Path, "exists", autospec=True, side_effect=exists)
        else:
            mocker.patch.object(Path, "exists", autospec=True, return_value=exists)
        if callable(read_text):
            mocker.patch.object(Path, "read_text", autospec=True, side_effect=read_text)
        else:
            mocker.patch.object(Path, "read_text", autospec=True, return_value=read_text)

    return _factory


@pytest.fixture
def mock_sessions_fixture(mocker):
    """Fixture that patches session-related functions (get_lincona_home, list_sessions, delete_session)."""

    def _factory(
        home: Path | None = None,
        sessions: list[Any] | None = None,
        delete_side_effect: Any | None = None,
        patch_delete: bool = False,
    ):
        """Create mocks for session-related functions.

        Args:
            home: Path to return from get_lincona_home (default: /virtual/home)
            sessions: List of sessions to return from list_sessions (default: empty list)
            delete_side_effect: Side effect for delete_session (only used if patch_delete=True)
            patch_delete: Whether to patch delete_session (default: False, to avoid conflicts)
        """
        if home is None:
            home = Path("/virtual/home")
        mocker.patch("lincona.cli.get_lincona_home", autospec=True, return_value=home)

        if sessions is not None:
            mocker.patch("lincona.cli.list_sessions", autospec=True, return_value=sessions)

        if patch_delete:
            if delete_side_effect is not None:
                mocker.patch("lincona.cli.delete_session", autospec=True, side_effect=delete_side_effect)
            else:
                mocker.patch("lincona.cli.delete_session", autospec=True)

    return _factory
