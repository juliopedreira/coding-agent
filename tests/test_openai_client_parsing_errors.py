import pytest

from lincona.openai_client.parsing import parse_stream
from lincona.openai_client.types import StreamingParseError


@pytest.mark.asyncio
async def test_tool_call_delta_missing_id_raises() -> None:
    async def gen():
        yield 'data: {"type":"tool_call_delta","delta":{"arguments_delta":"{}"}}\n'

    with pytest.raises(StreamingParseError):
        [e async for e in parse_stream(gen())]
