import json

import httpx
import pytest

import lincona.openai_client.transport as transport_mod
from lincona.config import AuthMode
from lincona.openai_client.transport import (
    AuthenticatedResponsesTransport,
    HttpResponsesTransport,
    OpenAISDKResponsesTransport,
    _map_openai_event,
)


class StubAuthManager:
    def __init__(
        self,
        *,
        mode: AuthMode,
        base_url: str,
        token: str,
        account_id: str | None = None,
    ) -> None:
        self._mode = mode
        self._base_url = base_url
        self._token = token
        self._account_id = account_id
        self.force_calls = 0

    async def get_access_token(self) -> str:
        return self._token

    async def force_refresh(self) -> None:
        self.force_calls += 1
        self._token = f"{self._token}-refreshed"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def account_id(self) -> str | None:
        return self._account_id

    @property
    def mode(self) -> AuthMode:
        return self._mode


@pytest.mark.asyncio
async def test_http_transport_streams_and_sets_headers(fake_http_client_factory) -> None:
    client = fake_http_client_factory()
    transport = HttpResponsesTransport(api_key="abc", client=client)

    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)

    await transport.aclose()
    await client.aclose()

    recorded = client.recorded
    assert recorded["method"] == "POST"
    assert recorded["url"] == "https://api.openai.com/v1/responses"
    assert recorded["payload"] == {"hello": "world"}
    assert recorded["headers"]["authorization"] == "Bearer abc"
    assert recorded["headers"]["content-type"] == "application/json"
    assert recorded["headers"]["user-agent"] == "lincona/0.1.0"
    assert recorded["headers"]["openai-beta"] == "responses=v1"
    assert chunks == ['data: {"delta":"hi"}', "data: [DONE]"]


@pytest.mark.asyncio
async def test_http_transport_raises_on_http_errors(error_response_handler, mock_http_client) -> None:
    handler = error_response_handler(status_code=429, text="rate limited")
    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"foo": "bar"}):
            pass

    await transport.aclose()
    await client.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_mock_transport_yields_chunks(mock_responses_transport) -> None:
    transport = mock_responses_transport(chunks=["one", b"two"])

    collected = []
    async for chunk in transport.stream_response({"ignored": True}):
        collected.append(chunk)

    assert collected == ["one", b"two"]


@pytest.mark.asyncio
async def test_mock_transport_errors(mock_transport_error) -> None:
    transport = mock_transport_error(status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({}):
            pass


@pytest.mark.asyncio
async def test_logging_hook_records_status_and_request_id(successful_response_handler, mock_http_client) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    handler = successful_response_handler(
        body='data: {"delta":"hi"}\n\ndata: [DONE]\n', headers={"x-request-id": "req-123"}
    )
    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda e, d: events.append((e, d)))

    async for _ in transport.stream_response({"hello": "world"}):
        pass

    await transport.aclose()
    await client.aclose()
    await client.aclose()

    assert events and events[0][0] == "response_complete"
    data = events[0][1]
    assert data["status"] == 200
    assert data["request_id"] == "req-123"
    assert data["base_url"] == "https://api.openai.com/v1"


def test_map_openai_event_text_and_tools() -> None:
    class Item:
        def __init__(self) -> None:
            self.type = "function_call"
            self.call_id = "call1"
            self.name = "echo"
            self.arguments = "{}"

    assert _map_openai_event(type("E", (), {"type": "response.output_text.delta", "delta": "hi"})) == {
        "type": "text_delta",
        "delta": {"text": "hi"},
    }
    start = type("E", (), {"type": "response.output_item.added", "item": Item()})
    assert _map_openai_event(start) == {
        "type": "tool_call_start",
        "delta": {"id": "call1", "name": "echo", "arguments": "{}"},
    }
    delta = type(
        "E",
        (),
        {"type": "response.function_call_arguments.delta", "item_id": "call1", "delta": "{}", "name": "echo"},
    )
    assert _map_openai_event(delta) == {
        "type": "tool_call_delta",
        "delta": {"id": "call1", "arguments_delta": "{}", "name": "echo"},
    }
    done = type(
        "E",
        (),
        {"type": "response.function_call_arguments.done", "item_id": "call1", "arguments": "{}", "name": "echo"},
    )
    assert _map_openai_event(done) == {
        "type": "tool_call_end",
        "delta": {"id": "call1", "arguments": "{}", "name": "echo"},
    }
    assert _map_openai_event(type("E", (), {"type": "response.completed"})) == {"type": "response.done"}


@pytest.mark.asyncio
async def test_sdk_transport_streams_events(fake_sdk_client_factory) -> None:
    events = [
        type("E", (), {"type": "response.output_text.delta", "delta": "hi"}),
        type("E", (), {"type": "response.completed"}),
    ]

    transport = OpenAISDKResponsesTransport(api_key="x", client=fake_sdk_client_factory(events))
    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)
    assert json.loads(chunks[0]) == {"type": "text_delta", "delta": {"text": "hi"}}


@pytest.mark.asyncio
async def test_http_transport_custom_headers_and_logger(mock_http_handler, mock_http_client):
    recorded = {}
    handler = mock_http_handler(
        status_code=200,
        text='data: {"type":"response.done"}\n',
        record_request=recorded,
    )
    client = mock_http_client(handler)
    events: list[tuple[str, dict[str, object]]] = []
    transport = HttpResponsesTransport(
        api_key="k",
        user_agent="ua",
        beta_header=None,
        client=client,
        logger=lambda e, d: events.append((e, d)),
    )

    async for _ in transport.stream_response({"x": 1}):
        pass
    await transport.aclose()
    await client.aclose()

    assert recorded["headers"]["user-agent"] == "ua"
    assert "openai-beta" not in recorded["headers"]
    assert events and events[0][0] == "response_complete"


@pytest.mark.asyncio
async def test_mock_transport_logger_called_on_success(mock_responses_transport):
    events = []
    transport = mock_responses_transport(chunks=["x"], logger=lambda e, d: events.append((e, d)))
    chunks = []
    async for c in transport.stream_response({}):
        chunks.append(c)
    assert events and events[0][0] == "response_complete"


@pytest.mark.asyncio
async def test_http_transport_aclose_owned_client():
    class DummyClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    dummy_client = DummyClient()
    transport = HttpResponsesTransport(api_key="k", client=dummy_client)
    await transport.aclose()
    assert dummy_client.closed is False  # not owned, so not closed


@pytest.mark.asyncio
async def test_sdk_transport_raises_http_status_with_body(failing_sdk_client_factory):
    failing_client = failing_sdk_client_factory(status_code=400, text="bad", url="https://api.test")
    transport = OpenAISDKResponsesTransport(api_key="x", client=failing_client)
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        async for _ in transport.stream_response({"hello": "world"}):
            pass
    assert "body=bad" in str(excinfo.value)


@pytest.mark.asyncio
async def test_authenticated_transport_sets_chatgpt_headers(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text='data: {"type":"response.done"}\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = StubAuthManager(
        mode=AuthMode.CHATGPT,
        base_url="https://chatgpt.com/backend-api/codex",
        token="tok",
        account_id="acct-123",
    )
    transport = AuthenticatedResponsesTransport(auth, client=client)

    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)

    await transport.aclose()
    assert chunks
    assert requests and str(requests[0].url) == "https://chatgpt.com/backend-api/codex/responses"
    assert requests[0].headers["Authorization"] == "Bearer tok"
    assert requests[0].headers["ChatGPT-Account-Id"] == "acct-123"


@pytest.mark.asyncio
async def test_authenticated_transport_refreshes_after_401(monkeypatch):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(401, text="unauthorized")
        return httpx.Response(200, text='data: {"type":"response.done"}\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = StubAuthManager(
        mode=AuthMode.CHATGPT,
        base_url="https://chatgpt.com/backend-api/codex",
        token="tok",
        account_id=None,
    )
    transport = AuthenticatedResponsesTransport(auth, client=client)

    chunks = []
    async for chunk in transport.stream_response({"foo": "bar"}):
        chunks.append(chunk)

    await transport.aclose()
    assert auth.force_calls == 1
    assert calls["count"] == 2
    assert chunks


@pytest.mark.asyncio
async def test_authenticated_transport_retries_rate_limit(monkeypatch):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, text="slow down", headers={"Retry-After": "3"})
        return httpx.Response(200, text='data: {"type":"response.done"}\n')

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(transport_mod.asyncio, "sleep", fake_sleep)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = StubAuthManager(mode=AuthMode.API_KEY, base_url="https://api.openai.com/v1", token="tok")
    transport = AuthenticatedResponsesTransport(auth, client=client)

    chunks = []
    async for chunk in transport.stream_response({"foo": "bar"}):
        chunks.append(chunk)

    await transport.aclose()
    assert calls["count"] == 2
    assert sleep_calls and sleep_calls[0] == 3.0
    assert chunks


def test_map_openai_event_unknown_returns_none():
    assert _map_openai_event(type("E", (), {"type": "unknown"})) is None


@pytest.mark.asyncio
async def test_http_transport_async_context_manager(successful_response_handler, mock_http_client):
    handler = successful_response_handler(body="data: [DONE]\n")
    client = mock_http_client(handler)
    async with HttpResponsesTransport(api_key="k", client=client) as transport:
        async for _ in transport.stream_response({"x": 1}):
            pass
    await client.aclose()


def test_map_openai_event_handles_non_string_delta():
    assert _map_openai_event(type("E", (), {"type": "response.output_text.delta", "delta": 123})) is None


def test_map_openai_event_missing_arguments_delta_returns_none():
    evt = type("E", (), {"type": "response.function_call_arguments.delta", "item_id": None, "delta": {}, "name": "n"})
    assert _map_openai_event(evt) is None


def test_map_openai_event_done_missing_call_id_returns_none():
    evt = type(
        "E", (), {"type": "response.function_call_arguments.done", "item_id": None, "arguments": "{}", "name": "n"}
    )
    assert _map_openai_event(evt) is None


# Consolidated extra transport tests
@pytest.mark.asyncio
async def test_retry_after_mapping_and_logging(error_response_handler, mock_http_client) -> None:
    calls = []
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return error_response_handler(status_code=429, text="rate", headers={"Retry-After": "5"})(request)

    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"hello": "world"}):
            pass

    await transport.aclose()
    await client.aclose()

    assert calls
    assert events == []


@pytest.mark.asyncio
async def test_aiter_lines_empty_lines_skipped(successful_response_handler, mock_http_client) -> None:
    handler = successful_response_handler(body="\n\n")
    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client)

    chunks = []
    async for c in transport.stream_response({"hello": "world"}):
        chunks.append(c)

    await transport.aclose()
    await client.aclose()

    assert chunks == []


def test_transport_requires_api_key() -> None:
    with pytest.raises(ValueError):
        HttpResponsesTransport(api_key=" ")


@pytest.mark.asyncio
async def test_transport_logs_on_completion(successful_response_handler, mock_http_client):
    events = []

    handler = successful_response_handler(
        body='data: {"delta":"hi"}\n\ndata: [DONE]\n', headers={"x-request-id": "req-1"}
    )
    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    async for _ in transport.stream_response({"hello": "world"}):
        pass
    await transport.aclose()
    await client.aclose()

    assert events
    assert events[0]["status"] == 200
    assert events[0]["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_retry_after_mapped(error_response_handler, mock_http_client):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return error_response_handler(status_code=429, text="rate", headers={"Retry-After": "5"})(request)

    client = mock_http_client(handler)
    transport = HttpResponsesTransport(api_key="abc", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"foo": "bar"}):
            pass
    await transport.aclose()
    await client.aclose()

    assert calls
