import typing

import pytest

from lincona.config import ReasoningEffort
from lincona.openai_client.types import (
    ApiAuthError,
    ApiClientError,
    ApiError,
    ApiRateLimitError,
    ApiServerError,
    ApiTimeoutError,
    ApplyPatchFreeform,
    ConversationRequest,
    DeltaChunk,
    ErrorEvent,
    Message,
    MessageDone,
    MessageRole,
    ResponseEvent,
    StreamingParseError,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallPayload,
    ToolCallStart,
    ToolDefinition,
)


def test_message_validation() -> None:
    with pytest.raises(ValueError):
        Message(role=MessageRole.USER, content="")

    msg = Message(role=MessageRole.TOOL, content="result", tool_call_id="tc_123")
    assert msg.role == MessageRole.TOOL
    assert msg.tool_call_id == "tc_123"

    with pytest.raises(ValueError):
        Message(role=MessageRole.TOOL, content="ok", tool_call_id="")


def test_tool_definition_validation() -> None:
    with pytest.raises(ValueError):
        ToolDefinition(name=" ", description="desc", parameters={})

    with pytest.raises(ValueError):
        ToolDefinition(name="tool", description=" ", parameters={})

    tool = ToolDefinition(name="tool", description="Useful", parameters={"type": "object"})
    assert tool.name == "tool"
    assert tool.description == "Useful"
    assert "type" in tool.parameters


def test_conversation_request_validation() -> None:
    msg = Message(role=MessageRole.USER, content="hi")

    with pytest.raises(ValueError):
        ConversationRequest(messages=[], model="gpt-4.1")

    with pytest.raises(ValueError):
        ConversationRequest(messages=[msg], model=" ")

    with pytest.raises(ValueError):
        ConversationRequest(messages=[msg], model="gpt-4.1", max_output_tokens=0)

    with pytest.raises(ValueError):
        ConversationRequest(messages=[msg], model="gpt-4.1", timeout=0)

    request = ConversationRequest(
        messages=[msg],
        model="gpt-4.1",
        reasoning_effort=ReasoningEffort.LOW,
        tools=[ToolDefinition(name="tool", description="desc", parameters={}), ApplyPatchFreeform()],
        max_output_tokens=128,
        metadata={"session_id": "abc"},
        timeout=30.0,
    )

    assert request.model == "gpt-4.1"
    assert isinstance(request.tools[1], ApplyPatchFreeform)

    # Allow model=None to defer to client defaults
    request_none = ConversationRequest(messages=[msg], model=None)
    assert request_none.model is None


def test_delta_and_tool_call_payload_validation() -> None:
    with pytest.raises(ValueError):
        ToolCallPayload(id=" ", name="run", arguments="{}")
    with pytest.raises(ValueError):
        ToolCallPayload(id="tc1", name=" ", arguments="{}")

    payload = ToolCallPayload(id="tc1", name="run", arguments='{"a": 1}')

    with pytest.raises(ValueError):
        DeltaChunk()

    delta = DeltaChunk(text=None, tool_call=payload)
    assert delta.tool_call == payload


def test_response_event_union() -> None:
    args = typing.get_args(ResponseEvent)
    assert TextDelta in args
    assert ToolCallStart in args
    assert ToolCallDelta in args
    assert ToolCallEnd in args
    assert MessageDone in args
    assert ErrorEvent in args


def test_text_and_tool_call_events_validation() -> None:
    with pytest.raises(ValueError):
        TextDelta(text="")

    with pytest.raises(ValueError):
        ToolCallDelta(tool_call_id=" ", arguments_delta="")
    with pytest.raises(ValueError):
        ToolCallDelta(tool_call_id="tc", arguments_delta="")

    payload = ToolCallPayload(id="tc1", name="run", arguments="{}")
    start = ToolCallStart(tool_call=payload)
    end = ToolCallEnd(tool_call=payload)

    assert start.tool_call == payload
    assert end.tool_call == payload


def test_error_hierarchy() -> None:
    assert issubclass(ApiAuthError, ApiError)
    assert issubclass(ApiRateLimitError, ApiError)
    assert issubclass(ApiTimeoutError, ApiError)
    assert issubclass(ApiServerError, ApiError)
    assert issubclass(ApiClientError, ApiError)
    assert issubclass(StreamingParseError, ApiError)
