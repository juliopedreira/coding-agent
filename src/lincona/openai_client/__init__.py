"""OpenAI Responses client package."""

from __future__ import annotations

from .client import OpenAIResponsesClient  # noqa: F401
from .parsing import DEFAULT_MAX_TOOL_BUFFER_BYTES, parse_stream  # noqa: F401
from .transport import (  # noqa: F401
    HttpResponsesTransport,
    MockResponsesTransport,
    OpenAISDKResponsesTransport,
    ResponsesTransport,
)
from .types import (  # noqa: F401
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
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallPayload,
    ToolCallStart,
    ToolDefinition,
    ToolSpecification,
)
