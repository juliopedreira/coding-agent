from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
import pytest

from lincona.config import ReasoningEffort
from lincona.openai_client.client import OpenAIResponsesClient, _map_status_error
from lincona.openai_client.transport import MockResponsesTransport
from lincona.openai_client.types import (
    ApiAuthError,
    ApiClientError,
    ApiRateLimitError,
    ApiServerError,
    ApiTimeoutError,
    ApplyPatchFreeform,
    ConversationRequest,
    Message,
    MessageRole,
    ToolDefinition,
)


class CapturingTransport:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.last_payload: Mapping[str, Any] | None = None

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        self.last_payload = payload
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_builds_payload_and_streams_events() -> None:
    transport = CapturingTransport(
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
    assert payload["messages"][0] == {"role": "user", "content": "hi"}
    assert payload["tools"][0]["function"]["name"] == "list_dir"
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["max_output_tokens"] == 128
    assert payload["metadata"] == {"session_id": "abc"}
    assert payload["timeout"] == 12.5
    assert len(events) == 2  # TextDelta + MessageDone


@pytest.mark.asyncio
async def test_includes_freeform_tool() -> None:
    transport = CapturingTransport(chunks=["data: [DONE]\n"])
    client = OpenAIResponsesClient(transport)

    request = ConversationRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="gpt-4.1-mini",
        tools=[ApplyPatchFreeform()],
    )

    await anext(client.submit(request))

    assert transport.last_payload is not None
    tool_payload = transport.last_payload["tools"][0]
    assert tool_payload["function"]["name"] == "apply_patch_freeform"
    assert "patch" in tool_payload["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_http_errors_are_mapped() -> None:
    transport = MockResponsesTransport([], status_code=401)
    client = OpenAIResponsesClient(transport)
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    with pytest.raises(ApiAuthError):
        async for _ in client.submit(request):
            pass

    transport = MockResponsesTransport([], status_code=429)
    client = OpenAIResponsesClient(transport)
    with pytest.raises(ApiRateLimitError):
        async for _ in client.submit(request):
            pass

    transport = MockResponsesTransport([], status_code=500)
    client = OpenAIResponsesClient(transport)
    with pytest.raises(ApiServerError):
        async for _ in client.submit(request):
            pass


@pytest.mark.asyncio
async def test_timeout_and_request_error_mapping() -> None:
    class TimeoutTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise httpx.ReadTimeout("timeout")

    client = OpenAIResponsesClient(TimeoutTransport())
    request = ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model="gpt-4.1")

    with pytest.raises(ApiTimeoutError):
        async for _ in client.submit(request):
            pass

    class RequestErrorTransport:
        async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
            raise httpx.RequestError("boom")

    client = OpenAIResponsesClient(RequestErrorTransport())
    with pytest.raises(ApiClientError):
        async for _ in client.submit(request):
            pass


def test_status_error_mapping_function() -> None:
    request = httpx.Request("POST", "https://example.com")
    resp_401 = httpx.Response(401, request=request)
    err = httpx.HTTPStatusError("auth", request=request, response=resp_401)
    assert isinstance(_map_status_error(err), ApiAuthError)

    resp_429 = httpx.Response(429, request=request)
    err = httpx.HTTPStatusError("rate", request=request, response=resp_429)
    assert isinstance(_map_status_error(err), ApiRateLimitError)

    resp_500 = httpx.Response(500, request=request)
    err = httpx.HTTPStatusError("server", request=request, response=resp_500)
    assert isinstance(_map_status_error(err), ApiServerError)

    resp_404 = httpx.Response(404, request=request)
    err = httpx.HTTPStatusError("client", request=request, response=resp_404)
    assert isinstance(_map_status_error(err), ApiClientError)


@pytest.mark.asyncio
async def test_defaults_applied_when_missing() -> None:
    transport = CapturingTransport(chunks=["data: [DONE]\n"])
    client = OpenAIResponsesClient(
        transport,
        default_model="gpt-4.1-mini",
        default_reasoning_effort="medium",
        default_timeout=5.0,
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
