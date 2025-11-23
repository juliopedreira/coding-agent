"""Streaming parsers that convert raw SSE lines into ResponseEvent objects."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

from lincona.openai_client.types import (
    MessageDone,
    ResponseEvent,
    StreamingParseError,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallPayload,
    ToolCallStart,
)

DEFAULT_MAX_TOOL_BUFFER_BYTES = 32 * 1024


def _iter_lines(chunk: str) -> Iterable[str]:
    """Split an SSE chunk into individual lines."""

    for line in chunk.splitlines():
        if line:
            yield line


class _ParserState:
    def __init__(self, max_tool_buffer_bytes: int) -> None:
        self.max_tool_buffer_bytes = max_tool_buffer_bytes
        self.tool_argument_buffers: dict[str, list[str]] = defaultdict(list)
        self.tool_names: dict[str, str] = {}

    def _append_tool_args(self, tool_call_id: str, delta: str) -> None:
        self.tool_argument_buffers[tool_call_id].append(delta)
        current = sum(len(part.encode("utf-8")) for part in self.tool_argument_buffers[tool_call_id])
        if current > self.max_tool_buffer_bytes:
            raise StreamingParseError(
                f"tool call {tool_call_id} exceeded max buffer of {self.max_tool_buffer_bytes} bytes"
            )

    def handle_json(self, payload: dict[str, Any]) -> list[ResponseEvent]:
        """Convert a parsed JSON payload into one or more ResponseEvent instances."""

        event_type = payload.get("type")
        events: list[ResponseEvent] = []

        if event_type == "text_delta":
            delta = payload.get("delta", {})
            text = delta.get("text")
            if not isinstance(text, str):
                raise StreamingParseError("text_delta missing text")
            events.append(TextDelta(text=text))
            return events

        if event_type == "tool_call_start":
            delta = payload.get("delta", {})
            tool_call = self._build_tool_call(delta, allow_empty_arguments=True)
            self.tool_names[tool_call.id] = tool_call.name
            if delta.get("arguments"):
                self._append_tool_args(tool_call.id, delta["arguments"])
            events.append(ToolCallStart(tool_call=tool_call))
            return events

        if event_type == "tool_call_delta":
            delta = payload.get("delta", {})
            tool_call_id = delta.get("id")
            arguments_delta = delta.get("arguments_delta")
            if not isinstance(tool_call_id, str) or not isinstance(arguments_delta, str):
                raise StreamingParseError("tool_call_delta missing id or arguments_delta")
            name = delta.get("name")
            if isinstance(name, str):
                self.tool_names[tool_call_id] = name
            self._append_tool_args(tool_call_id, arguments_delta)
            events.append(
                ToolCallDelta(
                    tool_call_id=tool_call_id,
                    arguments_delta=arguments_delta,
                    name=name if isinstance(name, str) else None,
                )
            )
            return events

        if event_type == "tool_call_end":
            delta = payload.get("delta", {})
            tool_call = self._build_tool_call(delta, use_buffer=True)
            events.append(ToolCallEnd(tool_call=tool_call))
            # cleanup buffers
            self.tool_argument_buffers.pop(tool_call.id, None)
            self.tool_names.pop(tool_call.id, None)
            return events

        if event_type == "response.done":
            finish_reason = payload.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise StreamingParseError("finish_reason must be a string when provided")
            events.append(MessageDone(finish_reason=finish_reason))
            return events

        raise StreamingParseError(f"unsupported event type: {event_type}")

    def _build_tool_call(
        self, delta: dict[str, Any], *, use_buffer: bool = False, allow_empty_arguments: bool = False
    ) -> ToolCallPayload:
        tool_call_id_val = delta.get("id")
        if not isinstance(tool_call_id_val, str) or not tool_call_id_val.strip():
            raise StreamingParseError("tool call id is required")
        tool_call_id = tool_call_id_val

        name_val = delta.get("name")
        name = name_val if isinstance(name_val, str) and name_val.strip() else self.tool_names.get(tool_call_id)
        arguments = delta.get("arguments")
        if use_buffer:
            buffered = "".join(self.tool_argument_buffers.get(tool_call_id, []))
            if buffered:
                arguments = buffered
        if not isinstance(name, str) or not name.strip():
            raise StreamingParseError("tool call name is required")
        if not isinstance(arguments, str):
            raise StreamingParseError("tool call arguments are required")
        if not arguments and not allow_empty_arguments:
            raise StreamingParseError("tool call arguments are required")
        return ToolCallPayload(id=tool_call_id, name=name, arguments=arguments)


async def parse_stream(
    chunks: AsyncIterator[str | bytes], *, max_tool_buffer_bytes: int = DEFAULT_MAX_TOOL_BUFFER_BYTES
) -> AsyncIterator[ResponseEvent]:
    """Parse SSE-style chunks into ResponseEvent objects."""

    state = _ParserState(max_tool_buffer_bytes=max_tool_buffer_bytes)

    async for raw in chunks:
        text = raw.decode("utf-8") if isinstance(raw, (bytes | bytearray)) else raw
        for line in _iter_lines(text):
            # Support "data:" prefix lines and [DONE] sentinel.
            if line.strip() in {"data: [DONE]", "[DONE]"}:
                yield MessageDone(finish_reason="stop")
                continue

            if line.startswith("data:"):
                content = line[len("data:") :].strip()
            else:
                content = line.strip()

            try:
                payload = json.loads(content)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise StreamingParseError(f"invalid JSON chunk: {content}") from exc

            for event in state.handle_json(payload):
                yield event


async def consume_stream(source: AsyncIterator[ResponseEvent], *, queue_max: int = 128) -> AsyncIterator[ResponseEvent]:
    """Consume a source iterator into a bounded queue to provide back-pressure.

    The source is drained in a background task; the consumer pulls from a
    bounded asyncio.Queue. If the consumer exits early, the producer task is
    cancelled to avoid leaks.
    """

    queue: asyncio.Queue[ResponseEvent | BaseException | _Sentinel] = asyncio.Queue(maxsize=queue_max)
    sentinel = _Sentinel()
    stop_event = asyncio.Event()

    async def _producer() -> None:
        src = cast(AsyncIterator[Any], source)
        try:
            async for item in src:
                await queue.put(item)
                if stop_event.is_set():
                    break
        except asyncio.CancelledError:
            return
        except BaseException as exc:  # propagate to consumer
            if not stop_event.is_set():
                with contextlib.suppress(Exception):
                    await queue.put(exc)
        finally:
            with contextlib.suppress(Exception):
                aclose = getattr(src, "aclose", None)
                if callable(aclose):
                    await aclose()
                if not stop_event.is_set():
                    try:
                        await queue.put(sentinel)
                    except RuntimeError:
                        return

    producer_task = asyncio.create_task(_producer())

    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, BaseException):
                raise item
            yield cast(ResponseEvent, item)
    finally:
        stop_event.set()
        producer_task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await producer_task


class _Sentinel:
    """Unique sentinel for queue termination."""

    pass


__all__ = ["parse_stream", "consume_stream", "DEFAULT_MAX_TOOL_BUFFER_BYTES"]
