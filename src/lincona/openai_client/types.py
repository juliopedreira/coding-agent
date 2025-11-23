"""Domain models for the OpenAI Responses client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias

from lincona.config import ReasoningEffort


class MessageRole(str, Enum):
    """Chat message roles supported by the Responses API."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """Single chat message sent to or received from the model."""

    role: MessageRole
    content: str
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("content cannot be empty")
        if self.tool_call_id is not None and not self.tool_call_id:
            raise ValueError("tool_call_id cannot be an empty string")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """JSON tool definition advertised to the Responses API."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name cannot be empty")
        if not self.description.strip():
            raise ValueError("tool description cannot be empty")


@dataclass(frozen=True, slots=True)
class ApplyPatchFreeform:
    """Marker for the freeform apply_patch tool advertisement."""

    name: str = "apply_patch_freeform"
    description: str = "Apply patch using freeform tool calls."


ToolSpecification: TypeAlias = ToolDefinition | ApplyPatchFreeform


@dataclass(frozen=True, slots=True)
class ConversationRequest:
    """Structured request used by the OpenAIResponsesClient."""

    messages: Sequence[Message]
    model: str | None
    reasoning_effort: ReasoningEffort | None = None
    tools: Sequence[ToolSpecification] = field(default_factory=tuple)
    max_output_tokens: int | None = None
    metadata: Mapping[str, str] | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.model, str) and not self.model.strip():
            raise ValueError("model cannot be empty string")
        if not self.messages:
            raise ValueError("messages cannot be empty")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive when provided")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive when provided")


@dataclass(frozen=True, slots=True)
class ToolCallPayload:
    """Tool call payload emitted by the Responses API."""

    id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tool call id cannot be empty")
        if not self.name.strip():
            raise ValueError("tool call name cannot be empty")
        # arguments may stream in incrementally; empty is permitted at start.


@dataclass(frozen=True, slots=True)
class DeltaChunk:
    """Low-level delta parsed from the streaming transport."""

    text: str | None = None
    tool_call: ToolCallPayload | None = None

    def __post_init__(self) -> None:
        if self.text is None and self.tool_call is None:
            raise ValueError("delta chunk must contain text or tool_call data")


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text delta cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolCallStart:
    tool_call: ToolCallPayload


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    tool_call_id: str
    arguments_delta: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip():
            raise ValueError("tool_call_id cannot be empty")
        if not self.arguments_delta:
            raise ValueError("arguments_delta cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolCallEnd:
    tool_call: ToolCallPayload


@dataclass(frozen=True, slots=True)
class MessageDone:
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    error: Exception


ResponseEvent: TypeAlias = TextDelta | ToolCallStart | ToolCallDelta | ToolCallEnd | MessageDone | ErrorEvent


class ApiError(Exception):
    """Base class for API-related errors."""


class ApiAuthError(ApiError):
    """Authentication/authorization error."""


class ApiRateLimitError(ApiError):
    """Rate limit exceeded."""


class ApiTimeoutError(ApiError):
    """Network timeout."""


class ApiServerError(ApiError):
    """5xx server error."""


class ApiClientError(ApiError):
    """4xx client-side error not covered by other errors."""


class StreamingParseError(ApiError):
    """Raised when a streaming chunk cannot be parsed."""


__all__ = [
    "ApiAuthError",
    "ApiClientError",
    "ApiError",
    "ApiRateLimitError",
    "ApiServerError",
    "ApiTimeoutError",
    "ApplyPatchFreeform",
    "ConversationRequest",
    "DeltaChunk",
    "ErrorEvent",
    "Message",
    "MessageDone",
    "MessageRole",
    "ResponseEvent",
    "StreamingParseError",
    "TextDelta",
    "ToolCallDelta",
    "ToolCallEnd",
    "ToolCallPayload",
    "ToolCallStart",
    "ToolDefinition",
    "ToolSpecification",
]
