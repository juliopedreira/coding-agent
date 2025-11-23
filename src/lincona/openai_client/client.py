"""OpenAI Responses client orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast

import httpx

from lincona.openai_client.parsing import DEFAULT_MAX_TOOL_BUFFER_BYTES, parse_stream
from lincona.openai_client.transport import ResponsesTransport
from lincona.openai_client.types import (
    ApiAuthError,
    ApiClientError,
    ApiError,
    ApiRateLimitError,
    ApiServerError,
    ApiTimeoutError,
    ApplyPatchFreeform,
    ConversationRequest,
    Message,
    ResponseEvent,
    StreamingParseError,
    ToolDefinition,
    ToolSpecification,
)


class OpenAIResponsesClient:
    """Async client that submits conversation requests and yields streaming events."""

    def __init__(
        self,
        transport: ResponsesTransport,
        *,
        max_tool_buffer_bytes: int = DEFAULT_MAX_TOOL_BUFFER_BYTES,
        default_model: str | None = None,
        default_reasoning_effort: str | None = None,
        default_timeout: float | None = None,
    ) -> None:
        self._transport = transport
        self._max_tool_buffer_bytes = max_tool_buffer_bytes
        self._default_model = default_model
        self._default_reasoning_effort = default_reasoning_effort
        self._default_timeout = default_timeout

    async def submit(self, request: ConversationRequest) -> AsyncIterator[ResponseEvent]:
        """Submit a conversation request and yield parsed streaming events."""

        payload = self._build_payload(request)
        try:
            stream_candidate = self._transport.stream_response(payload)
            stream: AsyncIterator[str | bytes]
            if hasattr(stream_candidate, "__aiter__"):
                stream = cast(AsyncIterator[str | bytes], stream_candidate)
            else:
                stream = await cast(Awaitable[AsyncIterator[str | bytes]], stream_candidate)

            async for event in parse_stream(stream, max_tool_buffer_bytes=self._max_tool_buffer_bytes):
                yield event
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError("request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise _map_status_error(exc) from exc
        except httpx.RequestError as exc:
            raise ApiClientError("request failed") from exc
        except StreamingParseError:
            raise
        except ApiError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise ApiError("unexpected error") from exc

    def _build_payload(self, request: ConversationRequest) -> dict[str, Any]:
        model = request.model or self._default_model
        if not model:
            raise ApiClientError("model is required")

        messages = [_message_to_dict(msg) for msg in request.messages]
        tools = [_tool_to_dict(tool) for tool in request.tools]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        reasoning_effort = request.reasoning_effort or self._default_reasoning_effort
        if reasoning_effort is not None:
            effort_value = reasoning_effort.value if hasattr(reasoning_effort, "value") else reasoning_effort
            payload["reasoning"] = {"effort": effort_value}

        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens

        if request.metadata:
            payload["metadata"] = dict(request.metadata)

        timeout = request.timeout if request.timeout is not None else self._default_timeout
        if timeout is not None:
            payload["timeout"] = timeout

        return payload


def _message_to_dict(message: Message) -> dict[str, Any]:
    data = {"role": message.role.value, "content": message.content}
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    return data


def _tool_to_dict(tool: ToolSpecification) -> dict[str, Any]:
    if isinstance(tool, ToolDefinition):
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
    if isinstance(tool, ApplyPatchFreeform):
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                },
            },
        }
    raise TypeError(f"Unsupported tool specification: {tool!r}")


def _map_status_error(exc: httpx.HTTPStatusError) -> ApiError:
    status = exc.response.status_code
    if status in (401, 403):
        return ApiAuthError(f"auth failed with status {status}")
    if status == 429:
        return ApiRateLimitError("rate limited")
    if status >= 500:
        return ApiServerError(f"server error {status}")
    return ApiClientError(f"request failed with status {status}")


__all__ = ["OpenAIResponsesClient", "_map_status_error"]
