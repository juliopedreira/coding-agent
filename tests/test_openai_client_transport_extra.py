import httpx

from lincona.openai_client.transport import HttpResponsesTransport


def test_transport_logs_on_completion(monkeypatch):
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = 'data: {"delta":"hi"}\n\ndata: [DONE]\n'
        return httpx.Response(200, text=body, headers={"x-request-id": "req-1"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client, logger=lambda name, data: events.append(data))

    async def run():
        async for _ in transport.stream_response({"hello": "world"}):
            pass
        await transport.aclose()
        await client.aclose()

    import asyncio

    asyncio.run(run())

    assert events
    assert events[0]["status"] == 200
    assert events[0]["request_id"] == "req-1"


def test_retry_after_mapped(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="rate", headers={"Retry-After": "5"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpResponsesTransport(api_key="abc", client=client)

    import asyncio

    import pytest

    async def run():
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in transport.stream_response({"foo": "bar"}):
                pass
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())

    assert calls
