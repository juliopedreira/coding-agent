import pytest

from lincona.openai_client.parsing import parse_stream
from lincona.openai_client.types import StreamingParseError, ToolCallStart


@pytest.mark.asyncio
async def test_finish_reason_type_error() -> None:
    async def gen():
        yield 'data: {"type":"response.done","finish_reason":123}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]


@pytest.mark.asyncio
async def test_unsupported_event_type() -> None:
    async def gen():
        yield 'data: {"type":"unknown"}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]


@pytest.mark.asyncio
async def test_tool_call_start_with_arguments_buffered() -> None:
    async def gen():
        yield 'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":"{}}"}}\n'

    events = [e async for e in parse_stream(gen())]
    assert any(isinstance(e, ToolCallStart) for e in events)
