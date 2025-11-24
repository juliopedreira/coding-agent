import pytest

from lincona.openai_client.parsing import parse_stream
from lincona.openai_client.types import MessageDone, StreamingParseError, TextDelta


@pytest.mark.asyncio
async def test_invalid_json_raises_parse_error() -> None:
    async def gen():
        yield "data: {notjson}\n"

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]


@pytest.mark.asyncio
async def test_done_seen_only_once() -> None:
    async def gen():
        yield "data: [DONE]\n"
        yield "data: [DONE]\n"

    events = [e async for e in parse_stream(gen())]
    assert len([e for e in events if isinstance(e, MessageDone)]) == 2


@pytest.mark.asyncio
async def test_text_and_done() -> None:
    async def gen():
        yield 'data: {"type":"text_delta","delta":{"text":"hi"}}\n'
        yield "[DONE]"

    events = [e async for e in parse_stream(gen())]
    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], MessageDone)
