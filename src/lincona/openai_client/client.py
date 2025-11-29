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
    ErrorEvent,
    Message,
    MessageRole,
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
        base_url: str | None = None,
    ) -> None:
        self._transport = transport
        self._max_tool_buffer_bytes = max_tool_buffer_bytes
        self._default_model = default_model
        self._default_reasoning_effort = default_reasoning_effort
        self._default_timeout = default_timeout
        self._base_url = base_url

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
            err: ApiError = ApiTimeoutError("request timed out")
            err.__cause__ = exc
            yield ErrorEvent(error=err)
        except httpx.HTTPStatusError as exc:
            mapped = _map_status_error(exc)
            mapped.__cause__ = exc
            yield ErrorEvent(error=mapped)
        except httpx.RequestError as exc:
            err = ApiClientError("request failed")
            err.__cause__ = exc
            yield ErrorEvent(error=err)
        except StreamingParseError as exc:
            yield ErrorEvent(error=exc)
        except ApiError as exc:
            yield ErrorEvent(error=exc)
        except Exception as exc:
            err = ApiError("unexpected error")
            err.__cause__ = exc
            yield ErrorEvent(error=err)

    def _build_payload(self, request: ConversationRequest) -> dict[str, Any]:
        model = request.model or self._default_model
        if not model:
            raise ApiClientError("model is required")

        inputs = [_message_to_content(msg) for msg in request.messages if _message_to_content(msg) is not None]
        tools = [_tool_to_dict(tool) for tool in request.tools]

        payload: dict[str, Any] = {
            "model": model,
            "input": inputs,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        reasoning_effort = request.reasoning_effort or self._default_reasoning_effort
        if reasoning_effort is not None:
            effort_value = reasoning_effort.value if hasattr(reasoning_effort, "value") else reasoning_effort
            payload.setdefault("reasoning", {})["effort"] = effort_value

        if request.verbosity is not None:
            verbosity_value = request.verbosity.value if hasattr(request.verbosity, "value") else request.verbosity
            payload.setdefault("reasoning", {})["verbosity"] = verbosity_value

        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens

        if request.metadata:
            payload["metadata"] = dict(request.metadata)

        timeout = request.timeout if request.timeout is not None else self._default_timeout
        if timeout is not None:
            payload["timeout"] = timeout

        if self._base_url:
            payload["base_url"] = self._base_url

        return payload


def _message_to_content(message: Message) -> dict[str, Any] | None:
    if message.role is MessageRole.TOOL:
        return None
    data = {"role": message.role.value, "content": message.content}
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    return data


def _tool_to_dict(tool: ToolSpecification) -> dict[str, Any]:
    if isinstance(tool, ToolDefinition):
        parameters = dict(tool.parameters)
        props = parameters.get("properties") or {}
        if isinstance(props, dict) and "required" not in parameters:
            parameters["required"] = list(props.keys())
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
            "strict": True,
        }
    if isinstance(tool, ApplyPatchFreeform):
        parameters = {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "additionalProperties": False,
        }
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
            "strict": True,
        }
    raise TypeError(f"Unsupported tool specification: {tool!r}")


def _map_status_error(exc: httpx.HTTPStatusError) -> ApiError:
    status = exc.response.status_code
    body = exc.response.text if exc.response is not None else ""
    suffix = f" body={body}" if body else ""
    retry_after = exc.response.headers.get("retry-after")
    retry_suffix = ""
    if retry_after:
        retry_suffix = f" (retry after {retry_after}s)"
    if status in (401, 403):
        return ApiAuthError(f"auth failed with status {status}{suffix}")
    if status == 429:
        return ApiRateLimitError(f"rate limited{retry_suffix}{suffix}")
    if status >= 500:
        return ApiServerError(f"server error {status}{suffix}")
    return ApiClientError(f"request failed with status {status}{suffix}")


__all__ = ["OpenAIResponsesClient", "_map_status_error"]
