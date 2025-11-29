import asyncio

import httpx
import pytest

import lincona.config
import lincona.openai_client.client as client_module
from lincona.config import ReasoningEffort
from lincona.openai_client.client import OpenAIResponsesClient, _map_status_error
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
@pytest.mark.parametrize(
    "status_code,expected_error_type",
    [
        (401, ApiAuthError),
        (429, ApiRateLimitError),
        (500, ApiServerError),
    ],
)
async def test_http_errors_are_mapped(
    mock_transport_error, conversation_request_factory, status_code: int, expected_error_type: type[ApiError]
) -> None:
    """Test that HTTP errors are correctly mapped to API error types using parameterization."""
    transport = mock_transport_error(status_code=status_code)
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()

    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, expected_error_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected_error_type",
    [
        (httpx.ReadTimeout("timeout"), ApiTimeoutError),
        (httpx.RequestError("boom"), ApiClientError),
    ],
)
async def test_timeout_and_request_error_mapping(
    error_transport_factory, conversation_request_factory, error: Exception, expected_error_type: type[ApiError]
) -> None:
    """Test that timeout and request errors are correctly mapped using parameterization."""
    transport = error_transport_factory(error)
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()

    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, expected_error_type)


@pytest.mark.asyncio
async def test_streaming_parse_error_yields_error_event(
    bad_json_transport_factory, conversation_request_factory
) -> None:
    transport = bad_json_transport_factory("data: {not-json")
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0], ErrorEvent)
    assert isinstance(events[0].error, StreamingParseError)


@pytest.mark.asyncio
async def test_api_error_passthrough(error_transport_factory, conversation_request_factory) -> None:
    transport = error_transport_factory(ApiRateLimitError("slow"))
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiRateLimitError)


@pytest.mark.asyncio
async def test_generic_exception_wrapped(error_transport_factory, conversation_request_factory) -> None:
    transport = error_transport_factory(ValueError("boom"))
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()
    events = [event async for event in client.submit(request)]
    assert isinstance(events[0].error, ApiError)
    assert str(events[0].error) == "unexpected error"


def test_build_payload_requires_model(mock_responses_transport) -> None:
    client = OpenAIResponsesClient(mock_responses_transport(chunks=[]))
    with pytest.raises(ApiClientError):
        client._build_payload(ConversationRequest(messages=[Message(role=MessageRole.USER, content="hi")], model=None))


def test_tool_to_dict_unsupported_type() -> None:
    class Unknown:
        pass

    with pytest.raises(TypeError):
        client_module._tool_to_dict(Unknown())  # type: ignore[arg-type]


def test_payload_includes_verbosity(mock_responses_transport) -> None:
    transport = mock_responses_transport(chunks=[])
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


@pytest.mark.parametrize(
    "status_code,headers,expected_error_type,error_message_contains",
    [
        (401, None, ApiAuthError, None),
        (429, None, ApiRateLimitError, None),
        (429, {"Retry-After": "2"}, ApiRateLimitError, "retry after 2"),
        (500, None, ApiServerError, None),
        (404, None, ApiClientError, None),
    ],
)
def test_status_error_mapping_function(
    httpx_request_factory,
    httpx_response_factory,
    status_code: int,
    headers: dict[str, str] | None,
    expected_error_type: type[ApiError],
    error_message_contains: str | None,
) -> None:
    """Test status error mapping using parameterization to reduce redundancy."""
    request = httpx_request_factory()
    response = httpx_response_factory(status_code=status_code, request=request, headers=headers)
    err = httpx.HTTPStatusError("test", request=request, response=response)

    mapped_error = _map_status_error(err)
    assert isinstance(mapped_error, expected_error_type)

    if error_message_contains:
        assert error_message_contains in str(mapped_error)
    elif status_code == 429 and headers is None:
        # Special case: 429 without retry header should not contain "retry"
        assert "retry" not in str(mapped_error)


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
async def test_streaming_tool_calls_round_trip(capturing_transport, conversation_request_factory) -> None:
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
    request = conversation_request_factory()

    events = [event async for event in client.submit(request)]

    kinds = [type(e).__name__ for e in events]
    assert kinds[:3] == ["ToolCallStart", "ToolCallDelta", "ToolCallDelta"]
    assert kinds[3] == "ToolCallEnd"
    assert kinds[-1] == "MessageDone"


@pytest.mark.asyncio
async def test_cancel_early_does_not_error(capturing_transport, conversation_request_factory) -> None:
    transport = capturing_transport(
        chunks=[
            'data: {"type":"text_delta","delta":{"text":"hi"}}\n',
            'data: {"type":"text_delta","delta":{"text":"there"}}\n',
            "data: [DONE]\n",
        ]
    )
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()

    received: list[str] = []
    async for event in client.submit(request):
        received.append(type(event).__name__)
        break  # stop early to simulate cancellation/back-pressure

    assert received == ["TextDelta"]


@pytest.mark.asyncio
async def test_backpressure_with_slow_consumer(gated_transport_factory, conversation_request_factory) -> None:
    gate = asyncio.Event()

    transport = gated_transport_factory(
        gate,
        [
            'data: {"type":"text_delta","delta":{"text":"one"}}\n',
            'data: {"type":"text_delta","delta":{"text":"two"}}\n',
            "data: [DONE]\n",
        ],
    )
    client = OpenAIResponsesClient(transport)
    request = conversation_request_factory()

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
