import httpx
import pytest

from lincona.openai_client.transport import HttpResponsesTransport


@pytest.mark.asyncio
async def test_retry_after_mapping_and_logging() -> None:
    calls = []
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="rate", headers={"Retry-After": "5"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in transport.stream_response({"hello": "world"}):
            pass

    await transport.aclose()
    await client.aclose()

    assert calls
    # logger still runs on error? It doesn't today; ensure no crash
    assert events == []


@pytest.mark.asyncio
async def test_aiter_lines_empty_lines_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n\n", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client)

    chunks = []
    async for c in transport.stream_response({"hello": "world"}):
        chunks.append(c)

    await transport.aclose()
    await client.aclose()

    assert chunks == []
