"""Transport abstraction for the OpenAI Responses client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol

import httpx


class ResponsesTransport(Protocol):
    """Protocol for streaming Responses API payloads."""

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
        """Stream raw chunks returned by the API."""


DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class HttpResponsesTransport:
    """httpx-based transport for the real OpenAI Responses API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty")

        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.timeout)

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        url = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with self._client.stream("POST", url, json=payload, headers=headers, timeout=self.timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                yield line

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpResponsesTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


class MockResponsesTransport:
    """In-memory transport that yields predefined chunks for tests/offline mode."""

    def __init__(self, chunks: Sequence[str | bytes], status_code: int = 200) -> None:
        self._chunks = list(chunks)
        self.status_code = status_code

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
        if self.status_code >= 400:
            request = httpx.Request("POST", "mock://responses")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("mock transport error", request=request, response=response)

        for chunk in self._chunks:
            yield chunk


__all__ = ["ResponsesTransport", "HttpResponsesTransport", "MockResponsesTransport"]
