import json
from typing import Any

import httpx
import pytest

from lincona.openai_client.transport import HttpResponsesTransport, MockResponsesTransport


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
    assert recorded["headers"]["openai-beta"] == "responses-2024-10-01"
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
