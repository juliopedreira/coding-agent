"""Transport abstraction for the OpenAI Responses client."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Protocol

import httpx
from openai import AsyncOpenAI

from lincona.auth import AuthManager
from lincona.config import AuthMode


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
        beta_header: str | None = "responses=v1",
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

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
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


class OpenAISDKResponsesTransport:
    """Transport backed by the official openai Python SDK (Responses API)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        beta_header: str | None = "responses=v1",
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty")

        self._beta_header = beta_header
        self._client = client or AsyncOpenAI(
            api_key=api_key.strip(),
            base_url=base_url,
            organization=organization,
            project=project,
        )

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
        extra_headers = {"OpenAI-Beta": self._beta_header} if self._beta_header else None
        request_payload = dict(payload)
        request_payload.pop("stream", None)
        try:
            stream = await self._client.responses.create(stream=True, extra_headers=extra_headers, **request_payload)
        except httpx.HTTPStatusError as exc:
            # Surface the error body to aid debugging
            text = exc.response.text if exc.response is not None else ""
            raise httpx.HTTPStatusError(f"{exc} body={text}", request=exc.request, response=exc.response) from exc

        async for event in stream:
            json_payload = _map_openai_event(event)
            if json_payload is None:
                continue
            yield json.dumps(json_payload)


def _map_openai_event(event: Any) -> dict[str, Any] | None:
    """Convert SDK response events into the internal JSON payloads parse_stream expects."""

    event_type = getattr(event, "type", "")

    if event_type == "response.output_text.delta":
        delta = getattr(event, "delta", None)
        if isinstance(delta, str):
            return {"type": "text_delta", "delta": {"text": delta}}
        return None

    if event_type == "response.output_item.added":
        item = getattr(event, "item", None)
        if item and getattr(item, "type", None) == "function_call":
            call_id = getattr(item, "id", None) or getattr(item, "call_id", None)
            name = getattr(item, "name", None)
            arguments = getattr(item, "arguments", "") or ""
            if call_id and name:
                return {"type": "tool_call_start", "delta": {"id": call_id, "name": name, "arguments": arguments}}
        return None

    if event_type == "response.function_call_arguments.delta":
        call_id = getattr(event, "item_id", None) or getattr(event, "call_id", None)
        arguments_delta = getattr(event, "delta", None)
        name = getattr(event, "name", None)
        if call_id and isinstance(arguments_delta, str):
            delta_payload: dict[str, Any] = {"id": call_id, "arguments_delta": arguments_delta}
            if isinstance(name, str):
                delta_payload["name"] = name
            return {"type": "tool_call_delta", "delta": delta_payload}
        return None

    if event_type == "response.function_call_arguments.done":
        call_id = getattr(event, "item_id", None) or getattr(event, "call_id", None)
        arguments = getattr(event, "arguments", None)
        name = getattr(event, "name", None)
        if call_id and isinstance(arguments, str):
            end_payload: dict[str, Any] = {"id": call_id, "arguments": arguments}
            if isinstance(name, str):
                end_payload["name"] = name
            return {"type": "tool_call_end", "delta": end_payload}
        return None

    if event_type == "response.completed":
        return {"type": "response.done"}

    return None


class AuthenticatedResponsesTransport:
    """Transport that obtains bearer tokens from AuthManager (API key or ChatGPT OAuth)."""

    def __init__(
        self,
        auth_manager: AuthManager,
        *,
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
        user_agent: str | None = "lincona/0.1.0",
        beta_header: str | None = "responses=v1",
        logger: Callable[[str, dict[str, object]], None] | None = None,
        max_rate_limit_retries: int = 6,
    ) -> None:
        self._auth = auth_manager
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self._owns_client = client is None
        self._user_agent = user_agent
        self._beta_header = beta_header
        self._logger = logger
        self._max_rate_limit_retries = max(0, max_rate_limit_retries)

    async def stream_response(self, payload: Mapping[str, Any]) -> AsyncIterator[str | bytes]:
        attempt = 0
        refreshed = False
        while True:
            token = await self._auth.get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            if self._user_agent:
                headers["User-Agent"] = self._user_agent
            if self._beta_header:
                headers["OpenAI-Beta"] = self._beta_header
            account_id = self._auth.account_id
            if account_id:
                headers["ChatGPT-Account-Id"] = account_id
            url = f"{self._auth.base_url.rstrip('/')}/responses"
            response = None
            start = time.perf_counter()
            try:
                async with self._client.stream(
                    "POST", url, json=payload, headers=headers, timeout=self._timeout
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        yield line
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                if status == 401 and self._auth.mode == AuthMode.CHATGPT and not refreshed:
                    await self._auth.force_refresh()
                    refreshed = True
                    continue
                if status == 429 and self._auth.mode == AuthMode.API_KEY and attempt < self._max_rate_limit_retries:
                    delay = _retry_delay(exc.response, attempt)
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.RequestError:
                raise
            else:
                if self._logger and response is not None:
                    duration = time.perf_counter() - start
                    self._logger(
                        "response_complete",
                        {
                            "status": response.status_code,
                            "request_id": response.headers.get("x-request-id"),
                            "duration_sec": duration,
                            "base_url": self._auth.base_url,
                        },
                    )
                return

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    base = min(60.0, max(1.0, 2**attempt))
    return base + random.uniform(0, 1)


__all__ = [
    "ResponsesTransport",
    "HttpResponsesTransport",
    "MockResponsesTransport",
    "OpenAISDKResponsesTransport",
    "AuthenticatedResponsesTransport",
]
