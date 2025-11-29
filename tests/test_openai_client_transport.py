import json

import httpx
import pytest

from lincona.openai_client.transport import HttpResponsesTransport, OpenAISDKResponsesTransport, _map_openai_event


@pytest.mark.asyncio
async def test_http_transport_streams_and_sets_headers(fake_http_client_factory) -> None:
    client = fake_http_client_factory()
    transport = HttpResponsesTransport(api_key="abc", client=client)

    chunks = []
    async for chunk in transport.stream_response({"hello": "world"}):
        chunks.append(chunk)

    await transport.aclose()

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
