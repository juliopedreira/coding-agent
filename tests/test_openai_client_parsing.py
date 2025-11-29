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
async def test_done_sentinel_mixed_lines() -> None:
    chunks = [
        'data: {"type":"text_delta","delta":{"text":"hi"}}',
        "[DONE]",
    ]

    events = await collect_events(chunks)
    assert isinstance(events[-1], MessageDone)


@pytest.mark.asyncio
async def test_invalid_json_raises_streaming_parse_error() -> None:
    chunks = ['data: {"type": "text_delta", }']

    with pytest.raises(StreamingParseError):
        await collect_events(chunks)


@pytest.mark.asyncio
async def test_buffer_limit_boundary_allows_exact_size() -> None:
    limit = 16
    payload = "x" * limit
    chunks = [
        'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        f'data: {{"type":"tool_call_delta","delta":{{"id":"tc1","arguments_delta":"{payload}"}}}}\n',
        'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"run","arguments":""}}\n',
    ]

    events = await collect_events(chunks, max_tool_buffer_bytes=limit)
    assert isinstance(events[-1], ToolCallEnd)


@pytest.mark.asyncio
async def test_consume_stream_propagates_errors_from_source() -> None:
    async def source():
        yield TextDelta(text="ok")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        async for _ in consume_stream(source()):
            pass


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


# Consolidated extra parsing tests
@pytest.mark.asyncio
async def test_tool_call_end_uses_buffered_arguments_extra() -> None:
    chunks = [
        'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"{","name":"run"}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"\\"a\\":1}"}}\n',
        'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"run","arguments":""}}\n',
    ]

    async def gen():
        for c in chunks:
            yield c

    events = [e async for e in parse_stream(gen())]
    end_event = next(e for e in events if isinstance(e, ToolCallEnd))
    assert end_event.tool_call.arguments == '{"a":1}'


@pytest.mark.asyncio
async def test_text_delta_missing_text_raises_extra() -> None:
    async def gen():
        yield 'data: {"type":"text_delta","delta":{}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]


@pytest.mark.asyncio
async def test_done_seen_only_once_extra() -> None:
    async def gen():
        yield "data: [DONE]\n"
        yield "data: [DONE]\n"

    events = [e async for e in parse_stream(gen())]
    assert len([e for e in events if isinstance(e, MessageDone)]) == 2


@pytest.mark.asyncio
async def test_text_and_done_extra() -> None:
    async def gen():
        yield 'data: {"type":"text_delta","delta":{"text":"hi"}}\n'
        yield "[DONE]"

    events = [e async for e in parse_stream(gen())]
    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], MessageDone)


@pytest.mark.asyncio
async def test_done_mixed_with_other_lines_extra() -> None:
    chunks = [
        'data: {"type":"text_delta","delta":{"text":"hi"}}\n',
        "data: [DONE]\n",
        'data: {"type":"text_delta","delta":{"text":"ignored"}}\n',
    ]

    async def gen():
        for c in chunks:
            yield c

    events = [e async for e in parse_stream(gen())]

    assert isinstance(events[0], TextDelta)
    assert any(isinstance(e, MessageDone) for e in events)


# Error-path coverage consolidated
@pytest.mark.asyncio
async def test_tool_call_delta_missing_id_raises_extra() -> None:
    async def gen():
        yield 'data: {"type":"tool_call_delta","delta":{"arguments_delta":"{}"}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]


@pytest.mark.asyncio
async def test_tool_call_start_missing_fields_raise_extra() -> None:
    async def gen():
        yield 'data: {"type":"tool_call_start","delta":{"name":"x","arguments":""}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]

    async def gen2():
        yield 'data: {"type":"tool_call_start","delta":{"id":"tc","arguments":""}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen2())]

    async def gen3():
        yield 'data: {"type":"tool_call_start","delta":{"id":"tc","name":"x","arguments":""}}\n'
        yield 'data: {"type":"tool_call_end","delta":{"id":"tc","name":"","arguments":""}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen3())]


@pytest.mark.asyncio
async def test_tool_call_arguments_missing_raises_extra() -> None:
    async def gen():
        yield 'data: {"type":"tool_call_end","delta":{"id":"tc","name":"run"}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]
