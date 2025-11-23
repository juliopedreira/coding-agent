"""Transport abstraction for the OpenAI Responses client."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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
        user_agent: str | None = "lincona/0.1.0",
        beta_header: str | None = "responses-2024-10-01",
        logger: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty")

        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.timeout)
        self._user_agent = user_agent
        self._beta_header = beta_header
        self._logger = logger

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        url = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self._beta_header:
            headers["OpenAI-Beta"] = self._beta_header

        start = time.perf_counter()
        async with self._client.stream("POST", url, json=payload, headers=headers, timeout=self.timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                yield line
        if self._logger:
            duration = time.perf_counter() - start
            self._logger(
                "response_complete",
                {
                    "status": response.status_code,
                    "request_id": response.headers.get("x-request-id"),
                    "duration_sec": duration,
                    "base_url": self.base_url,
                },
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpResponsesTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


class MockResponsesTransport:
    """In-memory transport that yields predefined chunks for tests/offline mode."""

    def __init__(
        self,
        chunks: Sequence[str | bytes],
        status_code: int = 200,
        logger: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self._chunks = list(chunks)
        self.status_code = status_code
        self._logger = logger

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
        if self.status_code >= 400:
            request = httpx.Request("POST", "mock://responses")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("mock transport error", request=request, response=response)

        for chunk in self._chunks:
            yield chunk
        if self._logger:
            self._logger(
                "response_complete",
                {"status": self.status_code, "request_id": None, "duration_sec": 0.0, "base_url": "mock://responses"},
            )


__all__ = ["ResponsesTransport", "HttpResponsesTransport", "MockResponsesTransport"]
