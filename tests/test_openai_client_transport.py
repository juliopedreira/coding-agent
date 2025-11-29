import json
from typing import Any

import httpx
import pytest

from lincona.openai_client.transport import (
    HttpResponsesTransport,
    MockResponsesTransport,
    OpenAISDKResponsesTransport,
    _map_openai_event,
)


@pytest.mark.asyncio
async def test_http_transport_streams_and_sets_headers() -> None:
    recorded: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["method"] = request.method
        recorded["url"] = str(request.url)
        recorded["headers"] = request.headers
        recorded["payload"] = json.loads(request.content.decode())
        body = 'data: {"delta":"hi"}\n\ndata: [DONE]\n'
        return httpx.Response(200, text=body, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client)

    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)

    await transport.aclose()
    await client.aclose()

    assert recorded["method"] == "POST"
    assert recorded["url"] == "https://api.openai.com/v1/responses"
    assert recorded["payload"] == {"hello": "world"}
    assert recorded["headers"]["authorization"] == "Bearer abc"
    assert recorded["headers"]["content-type"] == "application/json"
    assert recorded["headers"]["user-agent"] == "lincona/0.1.0"
    assert recorded["headers"]["openai-beta"] == "responses=v1"
    assert chunks == ['data: {"delta":"hi"}', "data: [DONE]"]


@pytest.mark.asyncio
async def test_http_transport_raises_on_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"foo": "bar"}):
            pass

    await transport.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_mock_transport_yields_chunks() -> None:
    transport = MockResponsesTransport(["one", b"two"])

    collected = []
    async for chunk in transport.stream_response({"ignored": True}):
        collected.append(chunk)

    assert collected == ["one", b"two"]


@pytest.mark.asyncio
async def test_mock_transport_errors() -> None:
    transport = MockResponsesTransport([], status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({}):
            pass


@pytest.mark.asyncio
async def test_logging_hook_records_status_and_request_id() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = 'data: {"delta":"hi"}\n\ndata: [DONE]\n'
        return httpx.Response(200, text=body, headers={"x-request-id": "req-123"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda e, d: events.append((e, d)))

    async for _ in transport.stream_response({"hello": "world"}):
        pass

    await transport.aclose()
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
async def test_sdk_transport_streams_events() -> None:
    events = [
        type("E", (), {"type": "response.output_text.delta", "delta": "hi"}),
        type("E", (), {"type": "response.completed"}),
    ]

    class FakeResponses:
        def __init__(self, evts):  # pragma: no cover - trivial
            self._events = evts

        async def create(self, **kwargs):
            async def gen():
                for e in self._events:
                    yield e

            return gen()

    class FakeClient:
        def __init__(self, evts):
            self.responses = FakeResponses(evts)

    transport = OpenAISDKResponsesTransport(api_key="x", client=FakeClient(events))
    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)
    assert json.loads(chunks[0]) == {"type": "text_delta", "delta": {"text": "hi"}}


def test_http_transport_custom_headers_and_logger(monkeypatch):
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["headers"] = dict(request.headers)
        recorded["url"] = str(request.url)
        body = 'data: {"type":"response.done"}\n'
        return httpx.Response(200, text=body, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events: list[tuple[str, dict[str, object]]] = []
    transport = HttpResponsesTransport(
        api_key="k",
        user_agent="ua",
        beta_header=None,
        client=client,
        logger=lambda e, d: events.append((e, d)),
    )

    async def run():
        async for _ in transport.stream_response({"x": 1}):
            pass
        await transport.aclose()
        await client.aclose()

    import asyncio

    asyncio.run(run())
    assert recorded["headers"]["user-agent"] == "ua"
    assert "openai-beta" not in recorded["headers"]
    assert events and events[0][0] == "response_complete"


@pytest.mark.asyncio
async def test_mock_transport_logger_called_on_success():
    events = []
    transport = MockResponsesTransport(["x"], logger=lambda e, d: events.append((e, d)))
    chunks = []
    async for c in transport.stream_response({}):
        chunks.append(c)
    assert events and events[0][0] == "response_complete"


@pytest.mark.asyncio
async def test_http_transport_aclose_owned_client():
    transport = HttpResponsesTransport(api_key="k")
    await transport.aclose()


@pytest.mark.asyncio
async def test_sdk_transport_raises_http_status_with_body():
    request = httpx.Request("POST", "https://api.test")
    response = httpx.Response(400, text="bad", request=request)

    class FailingClient:
        class responses:  # type: ignore[invalid-name]
            @staticmethod
            async def create(**kwargs):
                raise httpx.HTTPStatusError("boom", request=request, response=response)

    transport = OpenAISDKResponsesTransport(api_key="x", client=FailingClient())
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        async for _ in transport.stream_response({"hello": "world"}):
            pass
    assert "body=bad" in str(excinfo.value)


def test_map_openai_event_unknown_returns_none():
    assert _map_openai_event(type("E", (), {"type": "unknown"})) is None


@pytest.mark.asyncio
async def test_http_transport_async_context_manager():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="data: [DONE]\n", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
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
    evt = type("E", (), {"type": "response.function_call_arguments.done", "item_id": None, "arguments": "{}", "name": "n"})
    assert _map_openai_event(evt) is None


# Consolidated extra transport tests
@pytest.mark.asyncio
async def test_retry_after_mapping_and_logging() -> None:
    calls = []
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="rate", headers={"Retry-After": "5"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"hello": "world"}):
            pass

    await transport.aclose()
    await client.aclose()

    assert calls
    assert events == []


@pytest.mark.asyncio
async def test_aiter_lines_empty_lines_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n\n", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
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


def test_transport_logs_on_completion(monkeypatch):
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = 'data: {"delta":"hi"}\n\ndata: [DONE]\n'
        return httpx.Response(200, text=body, headers={"x-request-id": "req-1"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    async def run():
        async for _ in transport.stream_response({"hello": "world"}):
            pass
        await transport.aclose()
        await client.aclose()

    import asyncio

    asyncio.run(run())

    assert events
    assert events[0]["status"] == 200
    assert events[0]["request_id"] == "req-1"


def test_retry_after_mapped(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="rate", headers={"Retry-After": "5"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client)

    import asyncio
    import pytest

    async def run():
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in transport.stream_response({"foo": "bar"}):
                pass
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())

    assert calls
