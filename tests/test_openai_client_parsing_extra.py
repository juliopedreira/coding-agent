import pytest

from lincona.openai_client.parsing import parse_stream
from lincona.openai_client.types import MessageDone, TextDelta


@pytest.mark.asyncio
async def test_done_mixed_with_other_lines() -> None:
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
    assert isinstance(events[1], MessageDone)


@pytest.mark.asyncio
async def test_tool_call_roundtrip() -> None:
    chunks = [
        'data: {"type":"tool_call_start","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"{","name":"run"}}\n',
        'data: {"type":"tool_call_delta","delta":{"id":"tc1","arguments_delta":"\\"a\\":1}"}}\n',
        'data: {"type":"tool_call_end","delta":{"id":"tc1","name":"run","arguments":""}}\n',
        "data: [DONE]\n",
    ]

    async def gen():
        for c in chunks:
            yield c

    events = [e async for e in parse_stream(gen())]

    assert any(isinstance(e, MessageDone) for e in events)
