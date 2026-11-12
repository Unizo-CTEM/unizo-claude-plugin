"""SSO tests: a fake OIDC provider (mock transport) plus a real browser-style redirect to the loopback listener."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import socket
import stat
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp import Client

from unizo_mcp.auth import OidcAuth, TokenSet, TokenStore
from unizo_mcp.client import UnizoApiError, UnizoClient
from unizo_mcp.config import OidcSettings, Settings
from unizo_mcp.server import build_server

pytestmark = pytest.mark.anyio
ISSUER = "https://sso.example.com"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeIdP:
    """Records token requests; issues access tokens tok-1, tok-2, ..."""

    def __init__(self, rotate_refresh: bool = True, refresh_fails: bool = False) -> None:
        self.token_requests: list[dict[str, str]] = []
        self.rotate_refresh = rotate_refresh
        self.refresh_fails = refresh_fails
        self.transport = httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx2.Response(
                200,
                json={"authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token"},
            )
        if request.url.path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form["grant_type"] == "refresh_token" and self.refresh_fails:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            n = len(self.token_requests)
            body = {
                "access_token": f"tok-{n}",
                "expires_in": 3600,
                "id_token": jwt({"email": "analyst@example.com", "exp": 4_000_000_000}),
            }
            if form["grant_type"] == "authorization_code" or self.rotate_refresh:
                body["refresh_token"] = f"refresh-{n}"
            return httpx2.Response(200, json=body)
        return httpx2.Response(404)


def oidc_settings(tmp_path: Path, **overrides) -> OidcSettings:
    return OidcSettings(
        issuer=ISSUER,
        client_id="unizo-cli",
        redirect_port=free_port(),
        token_cache=tmp_path / "unizo" / "tokens.json",
        **overrides,
    )


def browser(callback_overrides: dict | None = None):
    """A fake browser: 'visits' the authorize URL and follows the IdP redirect back to the loopback listener.

    Like ``webbrowser.open`` with ``BROWSER=...`` set, it blocks until the page has loaded. If the server called it on
    the event loop thread, the callback could never be served (that deadlock was a real bug), so this regresses it."""
    visited: list[str] = []
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()

    def open_url(url: str) -> None:
        if threading.get_ident() == loop_thread:
            # Record it where the test sees it: the server swallows exceptions from the browser call.
            visited.append("ERROR: browser opened on the event loop thread")
            return
        visited.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        params = {"code": "auth-code", "state": q["state"], **(callback_overrides or {})}

        async def redirect() -> None:
            async with httpx2.AsyncClient() as http:
                await http.get(q["redirect_uri"].replace("localhost", "127.0.0.1"), params=params)

        asyncio.run_coroutine_threadsafe(redirect(), loop).result(timeout=5)

    return open_url, visited


async def test_login_uses_pkce_and_caches_tokens_privately(tmp_path: Path) -> None:
    idp = FakeIdP()
    settings = oidc_settings(tmp_path)
    open_url, visited = browser()
    auth = OidcAuth(settings, transport=idp.transport, open_browser=open_url)

    _, tokens = await auth.login(wait_seconds=5)
    await auth.aclose()

    assert not visited[0].startswith("ERROR"), visited[0]
    assert tokens is not None and tokens.access_token == "tok-1"
    q = {k: v[0] for k, v in parse_qs(urlsplit(visited[0]).query).items()}
    assert q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == f"http://localhost:{settings.redirect_port}/callback"
    exchange = idp.token_requests[0]
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "auth-code"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"].encode()).digest()).rstrip(b"=")
    assert challenge.decode() == q["code_challenge"]
    assert stat.S_IMODE(settings.token_cache.stat().st_mode) == 0o600
    assert auth.identity()["subject"] == "analyst@example.com"


async def test_login_rejects_wrong_state_and_keeps_waiting(tmp_path: Path) -> None:
    idp = FakeIdP()
    open_url, _ = browser({"state": "forged"})
    auth = OidcAuth(oidc_settings(tmp_path), transport=idp.transport, open_browser=open_url)

    url, tokens = await auth.login(wait_seconds=0.5)
    await auth.aclose()

    assert tokens is None and url.startswith(f"{ISSUER}/authorize?")
    assert idp.token_requests == []


async def test_idp_error_is_reported(tmp_path: Path) -> None:
    open_url, _ = browser({"error": "access_denied", "error_description": "User is not assigned to this app"})
    auth = OidcAuth(oidc_settings(tmp_path), transport=FakeIdP().transport, open_browser=open_url)
    with pytest.raises(Exception, match="not assigned"):
        await auth.login(wait_seconds=5)
    await auth.aclose()


async def test_expired_token_is_refreshed_and_old_refresh_token_kept(tmp_path: Path) -> None:
    idp = FakeIdP(rotate_refresh=False)
    settings = oidc_settings(tmp_path)
    TokenStore(settings.token_cache, f"{ISSUER}|unizo-cli").save(
        TokenSet(access_token="old", refresh_token="keep-me", expires_at=1.0)
    )
    auth = OidcAuth(settings, transport=idp.transport)

    assert await auth.bearer_token() == "tok-1"
    assert idp.token_requests[0] == {"grant_type": "refresh_token", "refresh_token": "keep-me", "client_id": "unizo-cli"}
    assert await auth.bearer_token() == "tok-1"  # cached, no second refresh
    assert len(idp.token_requests) == 1
    assert TokenStore(settings.token_cache, f"{ISSUER}|unizo-cli").load().refresh_token == "keep-me"
    await auth.aclose()


async def test_failed_refresh_clears_cache(tmp_path: Path) -> None:
    settings = oidc_settings(tmp_path)
    TokenStore(settings.token_cache, f"{ISSUER}|unizo-cli").save(
        TokenSet(access_token="old", refresh_token="revoked", expires_at=1.0)
    )
    auth = OidcAuth(settings, transport=FakeIdP(refresh_fails=True).transport)
    assert await auth.bearer_token() is None
    assert auth.identity() == {"logged_in": False}
    await auth.aclose()


async def test_id_token_mode_sends_id_token(tmp_path: Path) -> None:
    settings = oidc_settings(tmp_path, token_type="id")
    open_url, _ = browser()
    auth = OidcAuth(settings, transport=FakeIdP().transport, open_browser=open_url)
    _, tokens = await auth.login(wait_seconds=5)
    assert await auth.bearer_token() == tokens.id_token
    await auth.aclose()


# ── gateway client + MCP tools with SSO ──


def gateway(seen: list[httpx2.Request], reject: set[str] = frozenset()) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.headers.get("Authorization", "").removeprefix("Bearer ") in reject:
            return httpx2.Response(401)
        return httpx2.Response(200, json={"status": "UP"})

    return httpx2.MockTransport(handle)


async def test_client_retries_once_with_refreshed_token(tmp_path: Path) -> None:
    oidc = oidc_settings(tmp_path)
    TokenStore(oidc.token_cache, f"{ISSUER}|unizo-cli").save(
        TokenSet(access_token="revoked-at-gateway", refresh_token="r", expires_at=4_000_000_000)
    )
    auth = OidcAuth(oidc, transport=FakeIdP().transport)
    seen: list[httpx2.Request] = []
    settings = Settings(api_url="https://unizo.example", api_token="", oidc=oidc)
    client = UnizoClient(settings, transport=gateway(seen, reject={"revoked-at-gateway"}), auth=auth)

    assert await client.get("/health") == {"status": "UP"}
    assert [r.headers["Authorization"] for r in seen] == ["Bearer revoked-at-gateway", "Bearer tok-1"]
    await client.aclose()
    await auth.aclose()


async def test_client_asks_for_login_when_no_tokens(tmp_path: Path) -> None:
    oidc = oidc_settings(tmp_path)
    auth = OidcAuth(oidc, transport=FakeIdP().transport)
    client = UnizoClient(Settings(api_url="https://unizo.example", api_token="", oidc=oidc), auth=auth)
    with pytest.raises(UnizoApiError, match="unizo_login"):
        await client.get("/health")
    await client.aclose()
    await auth.aclose()


async def test_static_token_wins_over_sso(tmp_path: Path) -> None:
    seen: list[httpx2.Request] = []
    oidc = oidc_settings(tmp_path)
    settings = Settings(api_url="https://unizo.example", api_token="ci-token", oidc=oidc)
    client = UnizoClient(settings, transport=gateway(seen), auth=OidcAuth(oidc, transport=FakeIdP().transport))
    await client.get("/health")
    assert seen[0].headers["Authorization"] == "Bearer ci-token"
    await client.aclose()


async def test_login_and_status_tools(tmp_path: Path) -> None:
    oidc = oidc_settings(tmp_path)
    open_url, _ = browser()
    auth = OidcAuth(oidc, transport=FakeIdP().transport, open_browser=open_url)
    seen: list[httpx2.Request] = []
    settings = Settings(api_url="https://unizo.example", api_token="", oidc=oidc)
    server = build_server(settings, UnizoClient(settings, transport=gateway(seen), auth=auth), auth=auth)

    async with Client(server) as mcp:
        before = json.loads((await mcp.call_tool("unizo_status", {})).content[0].text)
        login = json.loads((await mcp.call_tool("unizo_login", {"wait_seconds": 5})).content[0].text)
        after = json.loads((await mcp.call_tool("unizo_status", {})).content[0].text)
        logout = json.loads((await mcp.call_tool("unizo_logout", {})).content[0].text)

    assert before["auth_mode"] == "sso" and before["sso"]["logged_in"] is False and before["reachable"] is False
    assert login["logged_in"] is True and login["subject"] == "analyst@example.com"
    assert after["reachable"] is True and seen[-1].headers["Authorization"] == "Bearer tok-1"
    assert logout["logged_in"] is False and auth.identity() == {"logged_in": False}


async def test_status_reports_sso_state_after_health_check(tmp_path: Path) -> None:
    """unizo_status must describe the session as it is after the call (refreshed or cleared), not before."""
    oidc = oidc_settings(tmp_path)
    TokenStore(oidc.token_cache, f"{ISSUER}|unizo-cli").save(
        TokenSet(access_token="stale", refresh_token="revoked", expires_at=1.0)
    )
    auth = OidcAuth(oidc, transport=FakeIdP(refresh_fails=True).transport)
    settings = Settings(api_url="https://unizo.example", api_token="", oidc=oidc)
    server = build_server(settings, UnizoClient(settings, transport=gateway([]), auth=auth), auth=auth)
    async with Client(server) as mcp:
        status = json.loads((await mcp.call_tool("unizo_status", {})).content[0].text)
    assert status["reachable"] is False and "unizo_login" in status["detail"]
    assert status["sso"]["logged_in"] is False
