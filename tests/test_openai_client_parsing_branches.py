import pytest

from lincona.openai_client.parsing import parse_stream
from lincona.openai_client.types import StreamingParseError, ToolCallEnd


@pytest.mark.asyncio
async def test_tool_call_end_uses_buffered_arguments() -> None:
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
async def test_text_delta_missing_text_raises() -> None:
    async def gen():
        yield 'data: {"type":"text_delta","delta":{}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]
