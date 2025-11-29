import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from lincona.auth import CHATGPT_BACKEND_URL, OPENAI_API_URL, AuthError, AuthManager
from lincona.config import AuthMode


def _encode_id_token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _write_token_file(
    path: Path, *, last_refresh_days: int = 9, claims: dict[str, str] | None = None
) -> dict[str, str]:
    now = datetime.now(UTC)
    claims = claims or {"chatgpt_account_id": "acct_old", "plan": "pro"}
    payload = {
        "access_token": "access-old",
        "refresh_token": "refresh-old",
        "id_token": _encode_id_token(claims),
        "claims": claims,
        "last_refresh": (now - timedelta(days=last_refresh_days)).isoformat(),
        "expires_at": (now - timedelta(days=1)).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


class FakeHttpClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.closed = False

    def post(self, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        self.calls.append((url, data))
        if not self.responses:
            raise AssertionError("no responses configured")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_auth_manager_api_key_mode_returns_key(tmp_path: Path) -> None:
    client = FakeHttpClient([])
    manager = AuthManager(
        auth_mode=AuthMode.API_KEY,
        api_key="sk-test",
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda url: True,
    )
    token = await manager.get_access_token()
    assert token == "sk-test"
    assert manager.base_url == OPENAI_API_URL
    assert manager.has_api_key() is True
    manager.close()


@pytest.mark.asyncio
async def test_auth_manager_refreshes_stale_tokens(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_token_file(auth_file, last_refresh_days=10)
    new_claims = {"chatgpt_account_id": "acct_new", "plan": "team"}
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://auth.openai.com/oauth/token"),
        json={
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "id_token": _encode_id_token(new_claims),
            "expires_in": 3600,
        },
    )
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda url: True,
    )
    token = await manager.get_access_token()
    assert token == "access-new"
    assert manager.account_id == "acct_new"
    assert manager.plan == "team"
    assert manager.base_url == CHATGPT_BACKEND_URL
    persisted = json.loads(auth_file.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "access-new"
    manager.close()


@pytest.mark.asyncio
async def test_auth_manager_refresh_failure_clears_cache(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_token_file(auth_file, last_refresh_days=10)
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://auth.openai.com/oauth/token"),
        json={"error": "invalid_grant"},
    )
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda url: True,
    )
    with pytest.raises(AuthError):
        await manager.get_access_token()
    assert not auth_file.exists()
    manager.close()


@pytest.mark.asyncio
async def test_auth_manager_force_refresh(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_token_file(auth_file, last_refresh_days=0)
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://auth.openai.com/oauth/token"),
        json={
            "access_token": "force-access",
            "refresh_token": "force-refresh",
            "id_token": _encode_id_token({"chatgpt_account_id": "forced"}),
            "expires_in": 120,
        },
    )
    client = FakeHttpClient([response])
    manager = AuthManager(
        auth_mode=AuthMode.CHATGPT,
        api_key=None,
        home=tmp_path,
        client_id="client",
        login_port=1500,
        http_client=client,
        browser_opener=lambda url: True,
    )
    creds = await manager.force_refresh()
    assert creds.access_token == "force-access"
    assert creds.refresh_token == "force-refresh"
    manager.close()
