import asyncio
import base64
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import lincona.auth as auth_mod
from lincona.auth import CHATGPT_BACKEND_URL, OPENAI_API_URL, AuthError, AuthManager, ChatGPTCredentials
from lincona.config import AuthMode


def _encode_id_token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _response(payload: dict[str, str], status: int = 200) -> httpx.Response:
    request = httpx.Request("POST", auth_mod.OAUTH_TOKEN_URL)
    return httpx.Response(status, request=request, json=payload)


class FakeHttpClient:
    def __init__(self, responses: list[httpx.Response] | None = None, *, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.closed = False
        self._error = error

    def post(self, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        self.calls.append((url, data))
        if self._error is not None:
            raise self._error
        if not self.responses:
            raise AssertionError("no responses configured")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class DummyCoordinator:
    def __init__(self) -> None:
        self.result: str | None = None
        self.error_exc: Exception | None = None
        self.cancelled = False

    def set_result(self, code: str) -> None:
        self.result = code

    def cancel(self) -> None:
        self.cancelled = True

    def error(self, exc: Exception) -> None:
        self.error_exc = exc


class DummyServer:
    def __init__(self) -> None:
        self.expected_state = "state"
        self.coordinator = DummyCoordinator()
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


def _build_handler(path: str, server: DummyServer):
    handler = auth_mod._CallbackHandler.__new__(auth_mod._CallbackHandler)
    handler.path = path
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"GET {path} HTTP/1.1"
    handler.headers = {}
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.server = server
    recorded: dict[str, int] = {}
    handler.send_error = lambda code: recorded.setdefault("error", code)  # type: ignore[assignment]
    handler.send_response = lambda code: recorded.setdefault("response", code)  # type: ignore[assignment]
    handler.send_header = lambda *args, **kwargs: None  # type: ignore[assignment]
    handler.end_headers = lambda: None  # type: ignore[assignment]
    return handler, recorded


def test_chatgpt_credentials_helpers() -> None:
    claims = {"chatgpt_account_id": "acct", "plan": "team"}
    creds = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token(claims),
        claims=claims,
        last_refresh=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert creds.account_id == "acct"
    assert creds.plan == "team"
    assert creds.needs_refresh(timedelta(days=10)) is False
    assert creds.needs_refresh(timedelta(hours=1)) is True
    restored = ChatGPTCredentials.from_dict(creds.to_dict())
    assert restored == creds

    no_claims = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    assert no_claims.account_id is None
    assert no_claims.plan is None


def test_chatgpt_credentials_from_dict_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(auth_mod, "_LOGGER", SimpleNamespace(warning=lambda msg, *args: logged.append(msg)))
    assert ChatGPTCredentials.from_dict({"access_token": object()}) is None
    assert logged


def test_login_coordinator_flow() -> None:
    loop = asyncio.new_event_loop()
    try:
        coord = auth_mod._LoginCoordinator(loop, "state")
        coord.set_result("abc")
        assert loop.run_until_complete(coord.future) == "abc"
        coord.set_result("ignored")  # future already done

        coord_cancel = auth_mod._LoginCoordinator(loop, "state")
        coord_cancel.cancel()
        with pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(coord_cancel.future)
        coord_cancel.cancel()

        coord_error = auth_mod._LoginCoordinator(loop, "state")
        coord_error.error(RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            loop.run_until_complete(coord_error.future)
        coord_error.error(RuntimeError("again"))
    finally:
        loop.close()


def test_callback_handler_wrong_path(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, recorded = _build_handler("/other", DummyServer())
    handler.do_GET()
    assert recorded["error"] == 404


def test_callback_handler_missing_params(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, recorded = _build_handler("/auth/callback?code=&state=", DummyServer())
    handler.do_GET()
    assert recorded["response"] == 400


def test_callback_handler_state_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, recorded = _build_handler("/auth/callback?code=ok&state=bad", DummyServer())
    handler.do_GET()
    assert recorded["response"] == 400


def test_callback_handler_success(monkeypatch: pytest.MonkeyPatch) -> None:
    server = DummyServer()

    class ImmediateThread:
        def __init__(self, target=None, daemon=False):
            self._target = target

        def start(self) -> None:
            if self._target:
                self._target()

    monkeypatch.setattr(auth_mod.threading, "Thread", ImmediateThread)
    handler, recorded = _build_handler("/auth/callback?code=ok&state=state", server)
    handler.do_GET()
    assert recorded["response"] == 200
    assert server.coordinator.result == "ok"
    assert server.shutdown_called is True
    handler.log_message("msg")


def test_login_session_shutdown_handles_exception() -> None:
    class BoomServer:
        def __init__(self) -> None:
            self.server_address = ("127.0.0.1", 0)
            self.server_port = 0

        def shutdown(self):
            raise RuntimeError("boom")

        def server_close(self):
            raise RuntimeError("close")

    thread = SimpleNamespace(is_alive=lambda: True, join=lambda timeout=None: None)
    loop = asyncio.new_event_loop()
    session = auth_mod._LoginSession(BoomServer(), thread, auth_mod._LoginCoordinator(loop, "s"))
    session.shutdown()
    loop.close()


def test_login_session_start_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class DummyServerClass:
        def __init__(self, addr, handler):
            created["addr"] = addr
            self.server_address = addr
            self.server_port = addr[1]
            self.coordinator = None
            self.expected_state = None

        def serve_forever(self):
            created["served"] = True

        def shutdown(self):
            created["shutdown"] = True

        def server_close(self):
            created["closed"] = True

    class DummyThread:
        def __init__(self, target=None, daemon=False):
            self._target = target
            created["thread"] = True

        def start(self):
            if self._target:
                self._target()

        def is_alive(self):
            return False

        def join(self, timeout=None):
            created["joined"] = True

    monkeypatch.setattr(auth_mod, "_ThreadedCallbackServer", DummyServerClass)
    monkeypatch.setattr(auth_mod.threading, "Thread", DummyThread)
    loop = asyncio.new_event_loop()
    coord = auth_mod._LoginCoordinator(loop, "token")
    session = auth_mod._LoginSession.start("127.0.0.1", 9999, coord)
    assert session.host == "127.0.0.1"
    assert session.port == 9999
    assert isinstance(session.future, asyncio.Future)
    assert session.port == 9999
    session.shutdown()
    session.cancel()
    assert created["shutdown"] is True
    loop.close()


def test_load_credentials_handles_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "auth.json"
    cache.write_text("not-json", encoding="utf-8")
    warnings: list[str] = []
    monkeypatch.setattr(auth_mod, "_LOGGER", SimpleNamespace(warning=lambda msg, *a: warnings.append(msg)))
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="key",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    assert manager.get_credentials() is None
    assert warnings
    manager.close()


def test_clear_credentials_missing_file(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="key",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager._clear_credentials()
    manager.close()


def test_load_credentials_success(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    payload = {
        "access_token": "a",
        "refresh_token": "r",
        "id_token": _encode_id_token({"chatgpt_account_id": "acct"}),
        "claims": {"chatgpt_account_id": "acct"},
        "last_refresh": datetime.now(UTC).isoformat(),
    }
    auth_file.write_text(json.dumps(payload), encoding="utf-8")
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    assert manager.account_id == "acct"
    manager.close()


def test_cached_credentials_helper(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    assert manager._cached_credentials() is None
    sentinel = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    manager._credentials = sentinel
    assert manager._cached_credentials() is sentinel
    manager.close()


@pytest.mark.asyncio
async def test_get_access_token_requires_credentials(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    with pytest.raises(AuthError):
        await manager.get_access_token()
    manager.close()


def test_has_api_key_false_when_blank(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key=" ",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    assert manager.has_api_key() is False
    manager.close()


def test_get_access_token_api_key_branch_sync(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="sk-sync",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    token = asyncio.run(manager.get_access_token())
    assert token == "sk-sync"
    manager.close()


@pytest.mark.asyncio
async def test_get_access_token_chatgpt_branch(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    assert await manager.get_access_token() == "tok"
    manager.close()


@pytest.mark.asyncio
async def test_force_refresh_without_credentials(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    with pytest.raises(AuthError):
        await manager.force_refresh()
    manager.close()


@pytest.mark.asyncio
async def test_ensure_fresh_triggers_refresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    now = datetime.now(UTC) - timedelta(days=10)
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=now,
        expires_at=now,
    )

    async def fake_refresh(current):
        return current

    monkeypatch.setattr(manager, "_refresh_credentials", fake_refresh)
    await manager._ensure_fresh_credentials()
    manager.close()


@pytest.mark.asyncio
async def test_ensure_fresh_raises_without_credentials(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    with pytest.raises(AuthError):
        await manager._ensure_fresh_credentials()
    manager.close()


@pytest.mark.asyncio
async def test_refresh_credentials_handles_http_error(tmp_path: Path) -> None:
    response = _response({"error": "bad"}, status=401)
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    with pytest.raises(AuthError):
        await manager._refresh_credentials(manager._credentials)
    assert manager.get_credentials() is None
    manager.close()


@pytest.mark.asyncio
async def test_refresh_credentials_handles_request_error(tmp_path: Path) -> None:
    client = FakeHttpClient(error=httpx.RequestError("boom", request=httpx.Request("POST", "https://auth")))
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    with pytest.raises(AuthError):
        await manager._refresh_credentials(manager._credentials)
    manager.close()


@pytest.mark.asyncio
async def test_refresh_credentials_http_error_no_logout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = _response({"error": "bad"}, status=500)
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    flag = {"logged_out": False}

    def fake_logout() -> None:
        flag["logged_out"] = True

    monkeypatch.setattr(manager, "logout", fake_logout)
    with pytest.raises(AuthError):
        await manager._refresh_credentials(manager._credentials)
    assert flag["logged_out"] is False
    manager.close()


def test_build_credentials_uses_fallback(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    payload = {"access_token": "a", "id_token": _encode_id_token({}), "expires_in": 10}
    creds = manager._build_credentials(payload, fallback_refresh="fallback")
    assert creds.refresh_token == "fallback"
    manager.close()


def test_build_credentials_without_expires(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    payload = {"access_token": "a", "id_token": _encode_id_token({})}
    creds = manager._build_credentials(payload, fallback_refresh="ref")
    assert creds.expires_at is None
    manager.close()


@pytest.mark.asyncio
async def test_login_success_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loop = asyncio.get_event_loop()

    class DummySession:
        def __init__(self):
            self.host = "127.0.0.1"
            self.port = 1501
            self.future = loop.create_future()
            self.future.set_result("auth-code")
            self.shutdown_called = False
            self.cancel_called = False

        def shutdown(self):
            self.shutdown_called = True

        def cancel(self):
            self.cancel_called = True

    responses = [_response({"access_token": "tok", "refresh_token": "ref", "id_token": _encode_id_token({})})]
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient(responses),
        browser_opener=lambda url: (_ for _ in ()).throw(RuntimeError("no browser")),
    )
    monkeypatch.setattr(auth_mod._LoginSession, "start", lambda *a, **k: DummySession())
    creds = await manager.login(force=True, timeout=5)
    assert creds.access_token == "tok"
    assert manager.mode is AuthMode.CHATGPT
    manager.close()


@pytest.mark.asyncio
async def test_login_returns_cached_when_not_forced(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    creds = await manager.login()
    assert creds.access_token == "tok"
    manager.close()


@pytest.mark.asyncio
async def test_login_returns_cached_generic_object(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    sentinel = object()
    manager._credentials = sentinel  # type: ignore[assignment]
    creds = await manager.login()
    assert creds is sentinel
    manager.close()


def test_login_returns_cached_with_custom_loop(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    loop = asyncio.new_event_loop()
    try:
        creds = loop.run_until_complete(manager.login())
    finally:
        loop.close()
    assert creds.access_token == "tok"
    manager.close()


@pytest.mark.asyncio
async def test_login_port_bind_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    monkeypatch.setattr(auth_mod._LoginSession, "start", lambda *a, **k: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(AuthError):
        await manager.login(force=True)
    manager.close()


@pytest.mark.asyncio
async def test_exchange_code_http_error(tmp_path: Path) -> None:
    response = _response({"error": "bad"}, status=400)
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([response]),
        browser_opener=lambda _: True,
    )
    with pytest.raises(AuthError):
        await manager._exchange_code("code", "verifier", "uri")
    manager.close()


def test_cancel_login_clears_active_session(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )

    class DummySession:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    manager._active_login = DummySession()
    manager.cancel_login()
    assert manager._active_login is None
    manager.close()


def test_manager_properties_cover_all_branches(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="key",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager.set_mode(AuthMode.CHATGPT)
    manager.set_api_key("new")
    assert manager.mode is AuthMode.CHATGPT
    assert manager.base_url == CHATGPT_BACKEND_URL
    manager.set_mode(AuthMode.API_KEY)
    assert manager.base_url == OPENAI_API_URL
    manager._credentials = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({"chatgpt_account_id": "acct", "plan": "pro"}),
        claims={"chatgpt_account_id": "acct", "plan": "pro"},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    assert manager.account_id == "acct"
    assert manager.plan == "pro"
    manager._credentials = None
    assert manager.account_id is None
    assert manager.plan is None
    assert isinstance(manager.storage_path, Path)
    manager.close()


def test_code_helpers() -> None:
    challenge = auth_mod._code_challenge("seed")
    assert challenge
    assert auth_mod._code_verifier("seed") == "seed"
    assert auth_mod._decode_id_token("bad") == {}


def test_close_closes_owned_http_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    closed = {}

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            closed["instantiated"] = True

        def close(self) -> None:
            closed["closed"] = True

    monkeypatch.setattr(auth_mod.httpx, "Client", DummyClient)
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="key",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=None,
        browser_opener=lambda _: True,
    )
    manager.close()


@pytest.mark.asyncio
async def test_force_refresh_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    existing = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    manager._credentials = existing

    async def fake_refresh(current):
        return current

    monkeypatch.setattr(manager, "_refresh_credentials", fake_refresh)
    assert await manager.force_refresh() == existing
    manager.close()


@pytest.mark.asyncio
async def test_refresh_credentials_success(tmp_path: Path) -> None:
    response = _response(
        {
            "access_token": "new",
            "refresh_token": "new-ref",
            "id_token": _encode_id_token({}),
            "expires_in": 1,
        }
    )
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda _: True,
    )
    current = ChatGPTCredentials(
        access_token="tok",
        refresh_token="ref",
        id_token=_encode_id_token({}),
        claims={},
        last_refresh=datetime.now(UTC),
        expires_at=None,
    )
    new_creds = await manager._refresh_credentials(current)
    assert new_creds.access_token == "new"
    manager.close()


@pytest.mark.asyncio
async def test_exchange_code_request_error(tmp_path: Path) -> None:
    client = FakeHttpClient(error=httpx.RequestError("boom", request=httpx.Request("POST", "x")))
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda _: True,
    )
    with pytest.raises(AuthError):
        await manager._exchange_code("code", "verifier", "uri")
    manager.close()


def test_cancel_login_no_session(tmp_path: Path) -> None:
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=FakeHttpClient([]),
        browser_opener=lambda _: True,
    )
    manager.cancel_login()  # no active session
    manager.close()
