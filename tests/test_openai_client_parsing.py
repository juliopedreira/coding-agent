import pytest

from lincona.openai_client.parsing import DEFAULT_MAX_TOOL_BUFFER_BYTES, consume_stream, parse_stream
from lincona.openai_client.types import (
    MessageDone,
    StreamingParseError,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallPayload,
    ToolCallStart,
)


async def collect_events(chunks: list[str], max_tool_buffer_bytes: int = DEFAULT_MAX_TOOL_BUFFER_BYTES):
    async def gen():
        for chunk in chunks:
            yield chunk

    return [event async for event in parse_stream(gen(), max_tool_buffer_bytes=max_tool_buffer_bytes)]


@pytest.mark.asyncio
async def test_consume_stream_bounded_queue_and_cancellation() -> None:
    produced = []

    async def source():
        for i in range(10):
            produced.append(i)
            yield TextDelta(text=str(i))

    async def consumer():
        results = []
        async for event in consume_stream(source(), queue_max=2):
            results.append(event.text)
            if len(results) == 3:
                break  # stop early to trigger cancellation
        return results

    results = await consumer()

    assert results == ["0", "1", "2"]
    # The helper should stop cleanly without propagating errors when consumer exits early.


@pytest.mark.asyncio
async def test_consume_stream_drains_all_items() -> None:
    async def source():
        for i in range(3):
            yield TextDelta(text=str(i))

    results = [e async for e in consume_stream(source(), queue_max=1)]

    assert [e.text for e in results] == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_parses_text_delta_and_done() -> None:
    chunks = [
        'data: {"type":"text_delta","delta":{"text":"hi"}}\n',
        "data: [DONE]\n",
    ]

    events = await collect_events(chunks)

    assert isinstance(events[0], TextDelta)
    assert events[0].text == "hi"
    assert isinstance(events[1], MessageDone)
    assert events[1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_tool_call_lifecycle() -> None:
    chunks = [
        'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"{","name":"run"}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"\\"a\\":1}"}}\n',
        'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"run","arguments":""}}\n',
    ]

    events = await collect_events(chunks)

    assert isinstance(events[0], ToolCallStart)
    assert events[0].tool_call.id == "tc1"

    assert isinstance(events[1], ToolCallDelta)
    assert events[1].arguments_delta == "{"
    assert isinstance(events[2], ToolCallDelta)
    assert events[2].arguments_delta == '"a":1}'

    assert isinstance(events[3], ToolCallEnd)
    payload: ToolCallPayload = events[3].tool_call
    assert payload.arguments == '{"a":1}'


@pytest.mark.asyncio
async def test_bytes_chunks_and_blank_lines_are_ignored() -> None:
    chunks = [
        b'data: {"type":"text_delta","delta":{"text":"hi"}}\n\n',
        b"\n",
    ]

    events = await collect_events(chunks)

    assert len(events) == 1
    assert isinstance(events[0], TextDelta)
    assert events[0].text == "hi"


@pytest.mark.asyncio
async def test_invalid_json_raises() -> None:
    chunks = ['data: {"type": "text_delta", }\n']

    with pytest.raises(StreamingParseError):
        await collect_events(chunks)


@pytest.mark.asyncio
async def test_buffer_limit_guard() -> None:
    over_limit = "x" * (DEFAULT_MAX_TOOL_BUFFER_BYTES + 1)
    chunks = [
        'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        f'data: {{"type":"tool_call_delta","delta":{{"id":"tc1","arguments_delta":"{over_limit}"}}}}\n',
    ]

    with pytest.raises(StreamingParseError):
        await collect_events(chunks)
