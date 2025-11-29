import asyncio
from typing import Any

import httpx
import pytest

import lincona.config
import lincona.openai_client.client as client_module
from lincona.config import ReasoningEffort
from lincona.openai_client.client import OpenAIResponsesClient, _map_status_error
from lincona.openai_client.transport import MockResponsesTransport
from lincona.openai_client.types import (
    ApiAuthError,
    ApiClientError,
    ApiError,
    ApiRateLimitError,
    ApiServerError,
    ApiTimeoutError,
    ApplyPatchFreeform,
    ConversationRequest,
    ErrorEvent,
    Message,
    MessageRole,
    StreamingParseError,
    ToolDefinition,
)


@pytest.mark.asyncio
async def test_builds_payload_and_streams_events(capturing_transport) -> None:
    transport = capturing_transport(
        chunks=[
            'data: {"type":"text_delta","delta":{"text":"hello"}}\n',
            "data: [DONE]\n",
        ]
    )
    client = OpenAIResponsesClient(transport)

    request = ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-4.1",
        reasoning_effort=ReasoningEffort.LOW,
        tools=[ToolDefinition(name="list_dir", description="List", parameters={})],
        max_output_tokens=128,
        metadata={"session_id": "abc"},
        timeout=12.5,
    )

    events = [event async for event in client.submit(request)]

    assert transport.last_payload is not None
    payload = transport.last_payload
    assert payload["model"] == "gpt-4.1"
    assert payload["input"][0] == {"role": "user", "content": "hi"}
    assert payload["tools"][0]["name"] == "list_dir"
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["max_output_tokens"] == 128
    assert payload["metadata"] == {"session_id": "abc"}
    assert payload["timeout"] == 12.5
    assert len(events) == 2  # TextDelta + MessageDone


@pytest.mark.asyncio
async def test_includes_freeform_tool(capturing_transport) -> None:
    transport = capturing_transport(chunks=["data: [DONE]\n"])
    client = OpenAIResponsesClient(transport)

    request = ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-4.1-mini",
        tools=[ApplyPatchFreeform()],
    )

    await anext(client.submit(request))

    assert transport.last_payload is not None
    tool_payload = transport.last_payload["tools"][0]
    assert tool_payload["name"] == "apply_patch_freeform"
    assert "patch" in tool_payload["parameters"]["properties"]


@pytest.mark.asyncio
async def test_tool_messages_are_filtered_from_payload(capturing_transport) -> None:
    transport = capturing_transport(chunks=["data: [DONE]\n"])
    client = OpenAIResponsesClient(transport)

    request = ConversationRequest(
        messages=[
            Message(role=MessageRole.USER, content="hi"),
            Message(role=MessageRole.TOOL, content='{"ok":true}', tool_call_id="tc1"),
            Message(role=MessageRole.ASSISTANT, content="result: ok"),
        ],
        model="gpt-4.1-mini",
    )

    await anext(client.submit(request))

    assert transport.last_payload is not None
    roles = [item["role"] for item in transport.last_payload["input"]]
    assert roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_http_errors_are_mapped() -> None:
    transport = MockResponsesTransport([], status_code=401)
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, ApiAuthError)

    transport = MockResponsesTransport([], status_code=429)
    client = OpenAIResponsesClient(transport)
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiRateLimitError)

    transport = MockResponsesTransport([], status_code=500)
    client = OpenAIResponsesClient(transport)
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiServerError)


@pytest.mark.asyncio
async def test_timeout_and_request_error_mapping() -> None:
    from collections.abc import AsyncIterator, Mapping

    class TimeoutTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise httpx.ReadTimeout("timeout")

    client = OpenAIResponsesClient(TimeoutTransport())
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, ApiTimeoutError)

    class RequestErrorTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise httpx.RequestError("boom")

    client = OpenAIResponsesClient(RequestErrorTransport())
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiClientError)


@pytest.mark.asyncio
async def test_streaming_parse_error_yields_error_event() -> None:
    from collections.abc import AsyncIterator, Mapping

    class BadTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            yield "data: {not-json"

    client = OpenAIResponsesClient(BadTransport())
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, StreamingParseError)


@pytest.mark.asyncio
async def test_api_error_passthrough() -> None:
    from collections.abc import AsyncIterator, Mapping

    class ApiErrorTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise ApiRateLimitError("slow")

    client = OpenAIResponsesClient(ApiErrorTransport())
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiRateLimitError)


@pytest.mark.asyncio
async def test_generic_exception_wrapped() -> None:
    from collections.abc import AsyncIterator, Mapping

    class BoomTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise ValueError("boom")

    client = OpenAIResponsesClient(BoomTransport())
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiError)
    assert str(events[0].error) == "unexpected error"


def test_build_payload_requires_model() -> None:
    client = OpenAIResponsesClient(MockResponsesTransport([]))
    with pytest.raises(ApiClientError):
        client._build_payload(ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model=None))


def test_tool_to_dict_unsupported_type() -> None:
    class Unknown:
        pass

    with pytest.raises(TypeError):
        client_module._tool_to_dict(Unknown())  # type: ignore[arg-type]


def test_payload_includes_verbosity() -> None:
    transport = MockResponsesTransport([])
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-4.1",
        verbosity=lincona.config.Verbosity.HIGH,
    )
    payload = client._build_payload(request)
    assert payload["reasoning"]["verbosity"] == "high"


def test_message_to_content_includes_tool_call_id() -> None:
    msg = Message(role=MessageRole.ASSISTANT, content="ok", tool_call_id="tc1")
    content = client_module._message_to_content(msg)
    assert content["tool_call_id"] == "tc1"


def test_status_error_mapping_function() -> None:
    request = httpx.Request("POST", "https://example.com")
    resp_401 = httpx.Response(401, request=request)
    err = httpx.HTTPStatusError("auth", request=request, response=resp_401)
    assert isinstance(_map_status_error(err), ApiAuthError)

    resp_429 = httpx.Response(429, request=request)
    err = httpx.HTTPStatusError("rate", request=request, response=resp_429)
    assert isinstance(_map_status_error(err), ApiRateLimitError)
    assert "retry" not in str(_map_status_error(err))

    resp_429_retry = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
    err = httpx.HTTPStatusError("rate", request=request, response=resp_429_retry)
    assert "retry after 2" in str(_map_status_error(err))

    resp_500 = httpx.Response(500, request=request)
    err = httpx.HTTPStatusError("server", request=request, response=resp_500)
    assert isinstance(_map_status_error(err), ApiServerError)

    resp_404 = httpx.Response(404, request=request)
    err = httpx.HTTPStatusError("client", request=request, response=resp_404)
    assert isinstance(_map_status_error(err), ApiClientError)


@pytest.mark.asyncio
async def test_defaults_applied_when_missing(capturing_transport) -> None:
    transport = capturing_transport(chunks=["data: [DONE]\n"])
    client = OpenAIResponsesClient(
        transport,
        default_model="gpt-4.1-mini",
        default_reasoning_effort="medium",
        default_timeout=5.0,
        base_url="https://mock.local",
    )

    request = ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model=None,  # use default model from client
        reasoning_effort=None,
        timeout=None,
    )

    await anext(client.submit(request))

    payload = transport.last_payload
    assert payload is not None
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["timeout"] == 5.0
    assert payload["base_url"] == "https://mock.local"


@pytest.mark.asyncio
async def test_streaming_tool_calls_round_trip(capturing_transport) -> None:
    transport = capturing_transport(
        chunks=[
            'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
            'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"{","name":"run"}}\n',
            'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"\\"a\\":1}"}}\n',
            'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"run","arguments":""}}\n',
            "data: [DONE]\n",
        ]
    )
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    events = [event async for event in client.submit(request)]

    kinds = [type(e).__name__ for e in events]
    assert kinds[:3] == ["ToolCallStart", "ToolCallDelta", "ToolCallDelta"]
    assert kinds[3] == "ToolCallEnd"
    assert kinds[-1] == "MessageDone"


@pytest.mark.asyncio
async def test_cancel_early_does_not_error(capturing_transport) -> None:
    transport = capturing_transport(
        chunks=[
            'data: {"type":"text_delta","delta":{"text":"hi"}}\n',
            'data: {"type":"text_delta","delta":{"text":"there"}}\n',
            "data: [DONE]\n",
        ]
    )
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    received: list[str] = []
    async for event in client.submit(request):
        received.append(type(event).__name__)
        break  # stop early to simulate cancellation/back-pressure

    assert received == ["TextDelta"]


@pytest.mark.asyncio
async def test_backpressure_with_slow_consumer() -> None:
    from collections.abc import AsyncIterator, Mapping

    gate = asyncio.Event()

    class GatedTransport:
        def __init__(self) -> None:
            self.started = False

        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            self.started = True
            yield 'data: {"type":"text_delta","delta":{"text":"one"}}\n'
            await gate.wait()
            yield 'data: {"type":"text_delta","delta":{"text":"two"}}\n'
            yield "data: [DONE]\n"

    transport = GatedTransport()
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    events_iter = client.submit(request)

    results = []

    async def consume() -> None:
        async for event in events_iter:
            results.append(event)
            if len(results) == 1:
                await asyncio.sleep(0)  # yield control without slowing the suite
                gate.set()

    await consume()

    assert len(results) == 3  # two TextDelta + MessageDone
