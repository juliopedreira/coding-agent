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
