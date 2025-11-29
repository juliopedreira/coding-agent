"""ChatGPT OAuth helpers for Lincona."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import logging
import secrets
import socketserver
import stat
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from lincona.config import AuthMode
from lincona.paths import get_lincona_home

_LOGGER = logging.getLogger(__name__)
OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_BACKEND_URL = "https://chatgpt.com/backend-api/codex"
OPENAI_API_URL = "https://api.openai.com/v1"
OAUTH_SCOPES = "openid profile email offline_access"
LOGIN_CALLBACK_PATH = "/auth/callback"
DEFAULT_REFRESH_INTERVAL = timedelta(days=8)
TOKEN_REQUEST_TIMEOUT = 30.0
SUCCESS_PAYLOAD = (
    """<!doctype html><html><body><h1>Signed in</h1><p>You can safely close this window.</p></body></html>"""
)


class AuthError(Exception):
    """Raised when any auth interaction fails."""


@dataclass(frozen=True)
class ChatGPTCredentials:
    access_token: str
    refresh_token: str
    id_token: str
    claims: dict[str, Any]
    last_refresh: datetime
    expires_at: datetime | None

    @property
    def account_id(self) -> str | None:
        candidates = ("chatgpt_account_id", "account_id")
        for name in candidates:
            value = self.claims.get(name)
            if isinstance(value, str) and value:
                return value
        return None

    @property
    def plan(self) -> str | None:
        plan = self.claims.get("plan")
        return plan if isinstance(plan, str) else None

    def needs_refresh(self, interval: timedelta) -> bool:
        now = datetime.now(UTC)
        if self.expires_at and now >= self.expires_at:
            return True
        return now - self.last_refresh >= interval

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "claims": self.claims,
            "last_refresh": self.last_refresh.isoformat(),
        }
        if self.expires_at:
            payload["expires_at"] = self.expires_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChatGPTCredentials | None:
        try:
            access_token = str(data["access_token"])
            refresh_token = str(data["refresh_token"])
            id_token = str(data["id_token"])
            claims = dict(data.get("claims") or {})
            last_refresh = datetime.fromisoformat(str(data["last_refresh"]))
            expires_at_value = data.get("expires_at")
            expires_at = datetime.fromisoformat(str(expires_at_value)) if expires_at_value is not None else None
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("failed to load saved tokens: %s", exc)
            return None
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            claims=claims,
            last_refresh=last_refresh,
            expires_at=expires_at,
        )


class _ThreadedCallbackServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _LoginCoordinator:
    def __init__(self, loop: asyncio.AbstractEventLoop, expected_state: str) -> None:
        self._loop = loop
        self._expected_state = expected_state
        self._future: asyncio.Future[str] = loop.create_future()

    @property
    def future(self) -> asyncio.Future[str]:
        return self._future

    @property
    def state(self) -> str:
        return self._expected_state

    def set_result(self, code: str) -> None:
        if not self._future.done():
            self._loop.call_soon_threadsafe(self._future.set_result, code)

    def cancel(self) -> None:
        if not self._future.done():
            self._loop.call_soon_threadsafe(self._future.cancel)

    def error(self, exc: Exception) -> None:
        if not self._future.done():
            self._loop.call_soon_threadsafe(self._future.set_exception, exc)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != LOGIN_CALLBACK_PATH:
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if not code or not state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing code or state")
            self.server.coordinator.error(AuthError("missing code or state"))  # type: ignore[attr-defined]
            return
        if state != self.server.expected_state:  # type: ignore[attr-defined]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"invalid state")
            self.server.coordinator.error(AuthError("state mismatch"))  # type: ignore[attr-defined]
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(SUCCESS_PAYLOAD.encode("utf-8"))
        self.server.coordinator.set_result(code)  # type: ignore[attr-defined]
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format: str, *args: object) -> None:  # pragma: no cover - avoid stdout spam
        return


class _LoginSession:
    def __init__(
        self, server: _ThreadedCallbackServer, thread: threading.Thread, coordinator: _LoginCoordinator
    ) -> None:
        self._server = server
        self._thread = thread
        self._coordinator = coordinator

    @property
    def host(self) -> str:
        return str(self._server.server_address[0])

    @property
    def port(self) -> int:
        return self._server.server_port

    @property
    def future(self) -> asyncio.Future[str]:
        return self._coordinator.future

    def cancel(self) -> None:
        self.shutdown()
        self._coordinator.cancel()

    def shutdown(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # pragma: no cover - defensive
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    @classmethod
    def start(cls, host: str, port: int, coordinator: _LoginCoordinator) -> _LoginSession:
        server = _ThreadedCallbackServer((host, port), _CallbackHandler)
        server.coordinator = coordinator  # type: ignore[attr-defined]
        server.expected_state = coordinator.state  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return cls(server, thread, coordinator)


class AuthManager:
    def __init__(
        self,
        *,
        auth_mode: AuthMode,
        api_key: str | None,
        home: Path | None = None,
        client_id: str,
        login_port: int,
        refresh_interval: timedelta = DEFAULT_REFRESH_INTERVAL,
        http_client: httpx.Client | None = None,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self._auth_mode = auth_mode
        self._api_key = api_key
        self._client_id = client_id
        self._login_port = login_port
        self._refresh_interval = refresh_interval
        self._home = (home or get_lincona_home()).expanduser()
        self._storage_path = self._home / "auth.json"
        self._lock = threading.RLock()
        self._http_client = http_client or httpx.Client(timeout=TOKEN_REQUEST_TIMEOUT)
        self._owns_client = http_client is None
        self._browser_opener = browser_opener or webbrowser.open
        self._credentials = self._load_credentials()
        self._active_login: _LoginSession | None = None

    def _load_credentials(self) -> ChatGPTCredentials | None:
        if not self._storage_path.exists():
            return None
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("failed to read auth cache: %s", exc)
            return None
        return ChatGPTCredentials.from_dict(data)

    def _persist_credentials(self, credentials: ChatGPTCredentials) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(credentials.to_dict(), indent=2), encoding="utf-8")
        temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temp_path.replace(self._storage_path)

    def _clear_credentials(self) -> None:
        try:
            self._storage_path.unlink()
        except FileNotFoundError:  # pragma: no cover - defensive
            pass
        self._credentials = None

    def set_mode(self, mode: AuthMode) -> None:
        with self._lock:
            self._auth_mode = mode

    def set_api_key(self, key: str | None) -> None:
        with self._lock:
            self._api_key = key

    @property
    def mode(self) -> AuthMode:
        return self._auth_mode

    @property
    def base_url(self) -> str:
        return CHATGPT_BACKEND_URL if self._auth_mode == AuthMode.CHATGPT else OPENAI_API_URL

    @property
    def account_id(self) -> str | None:
        with self._lock:
            return self._credentials.account_id if self._credentials else None

    @property
    def plan(self) -> str | None:
        with self._lock:
            return self._credentials.plan if self._credentials else None

    async def get_access_token(self) -> str:
        if self._auth_mode == AuthMode.CHATGPT:
            return (await self._ensure_fresh_credentials()).access_token
        if self._api_key:
            return self._api_key
        raise AuthError("openai API credentials are not configured")

    async def _ensure_fresh_credentials(self) -> ChatGPTCredentials:
        with self._lock:
            credentials = self._credentials
        if not credentials:
            raise AuthError("chatgpt login required")
        if credentials.needs_refresh(self._refresh_interval):
            credentials = await self._refresh_credentials(credentials)
        return credentials

    async def _refresh_credentials(self, current: ChatGPTCredentials) -> ChatGPTCredentials:
        payload = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": current.refresh_token,
        }
        try:
            response = await asyncio.to_thread(self._http_client.post, OAUTH_TOKEN_URL, data=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in {400, 401, 403}:
                self.logout()
            raise AuthError("token refresh failed") from exc
        except httpx.RequestError as exc:
            raise AuthError("token refresh failed") from exc
        raw = response.json()
        credentials = self._build_credentials(raw, fallback_refresh=current.refresh_token)
        with self._lock:
            self._credentials = credentials
            self._persist_credentials(credentials)
        return credentials

    def _build_credentials(
        self,
        payload: Mapping[str, Any],
        fallback_refresh: str | None = None,
    ) -> ChatGPTCredentials:
        access_token = str(payload["access_token"])
        refresh_token = str(payload.get("refresh_token") or fallback_refresh or "")
        id_token = str(payload["id_token"])
        claims = _decode_id_token(id_token)
        expires_at = None
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, int | float) and expires_in > 0:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
        last_refresh = datetime.now(UTC)
        return ChatGPTCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            claims=claims,
            last_refresh=last_refresh,
            expires_at=expires_at,
        )

    async def login(self, *, force: bool = False, timeout: float = 120.0) -> ChatGPTCredentials:
        if not force:
            with self._lock:
                existing = self._credentials
            if existing:
                return existing
        loop = asyncio.get_running_loop()
        coordinator = _LoginCoordinator(loop, secrets.token_urlsafe(24))
        try:
            session = _LoginSession.start("127.0.0.1", self._login_port, coordinator)
        except OSError as exc:  # pragma: no cover - port binding edge
            raise AuthError(f"failed to bind login port {self._login_port}: {exc}") from exc
        with self._lock:
            self._active_login = session
        try:
            redirect_uri = f"http://{session.host}:{session.port}{LOGIN_CALLBACK_PATH}"
            code_verifier = secrets.token_urlsafe(64)
            params = {
                "client_id": self._client_id,
                "response_type": "code",
                "scope": OAUTH_SCOPES,
                "redirect_uri": redirect_uri,
                "code_challenge": _code_challenge(code_verifier),
                "code_challenge_method": "S256",
                "state": coordinator.state,
                "id_token_add_organizations": "true",
                "prompt": "login",
            }
            auth_url = f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
            try:
                self._browser_opener(auth_url)
            except Exception:  # pragma: no cover - best effort
                _LOGGER.debug("browser open failed")
            # Display the URL in case auto-open fails
            print(f"Please open this URL to sign in: {auth_url}")
            code = await asyncio.wait_for(session.future, timeout=timeout)
        finally:
            session.shutdown()
            with self._lock:
                self._active_login = None
        credentials = await self._exchange_code(code, code_verifier, redirect_uri)
        with self._lock:
            self._credentials = credentials
            self._persist_credentials(credentials)
            self._auth_mode = AuthMode.CHATGPT
        return credentials

    async def _exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> ChatGPTCredentials:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        try:
            response = await asyncio.to_thread(self._http_client.post, OAUTH_TOKEN_URL, data=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AuthError("failed to redeem authorization code") from exc
        except httpx.RequestError as exc:
            raise AuthError("failed to redeem authorization code") from exc
        return self._build_credentials(response.json())

    def cancel_login(self) -> None:
        with self._lock:
            session = self._active_login
        if session:
            session.cancel()
            with self._lock:
                self._active_login = None

    def logout(self) -> None:
        with self._lock:
            self._credentials = None
            self._auth_mode = AuthMode.API_KEY
        self._clear_credentials()

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()


def _code_challenge(value: str) -> str:
    verifier = _code_verifier(value)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _code_verifier(seed: str) -> str:
    return seed


def _decode_id_token(token: str) -> dict[str, Any]:
    try:
        _, payload, *_ = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        chunk = base64.urlsafe_b64decode(padded)
        return json.loads(chunk)
    except Exception:  # pragma: no cover - best effort
        return {}


__all__ = [
    "AuthManager",
    "AuthError",
    "ChatGPTCredentials",
    "CHATGPT_BACKEND_URL",
    "OPENAI_API_URL",
]
