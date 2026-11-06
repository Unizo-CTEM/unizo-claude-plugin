"""SSO for the CTEM gateway: OAuth 2.0 authorization code + PKCE against any OIDC provider.

Flow: ``begin_login`` starts a one-shot HTTP listener on ``localhost:{redirect_port}``, builds the authorize URL
and (optionally) opens the browser. The IdP redirects back to ``/callback`` with a code, which is exchanged for
tokens. Tokens are cached on disk (mode 0600) and refreshed with the refresh token when they expire, so the user
only logs in again when the refresh token itself is gone.

Tokens are passed through to the gateway, which is what validates them. Claims are decoded here only to show the
user who they are logged in as; nothing here trusts them for access decisions.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import secrets
import time
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2

from unizo_ctem_mcp.config import OidcSettings

EXPIRY_SKEW_SECONDS = 60


class SsoError(Exception):
    """An SSO failure with a message the user can act on."""


@dataclass
class TokenSet:
    access_token: str
    id_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    """Epoch seconds when the token we send to the gateway expires. 0 means unknown (treat as valid)."""


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Reads a JWT payload *without* verifying it. Display only."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}


class TokenStore:
    """One JSON file holding tokens per (issuer, client_id). Written atomically with owner-only permissions."""

    def __init__(self, path: Path, key: str) -> None:
        self._path = path
        self._key = key

    def _read_all(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _write_all(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._path)

    def load(self) -> TokenSet | None:
        entry = self._read_all().get(self._key)
        return TokenSet(**entry) if entry else None

    def save(self, tokens: TokenSet) -> None:
        data = self._read_all()
        data[self._key] = asdict(tokens)
        self._write_all(data)

    def delete(self) -> None:
        data = self._read_all()
        if data.pop(self._key, None) is not None:
            self._write_all(data)


@dataclass
class PendingLogin:
    url: str
    done: asyncio.Future[TokenSet]


class OidcAuth:
    def __init__(
        self,
        settings: OidcSettings,
        transport: httpx2.AsyncBaseTransport | None = None,
        open_browser: Callable[[str], Any] = webbrowser.open,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._http = httpx2.AsyncClient(timeout=20.0, transport=transport, headers={"Accept": "application/json"})
        self._open_browser = open_browser
        self._clock = clock
        self._store = TokenStore(settings.token_cache, f"{settings.issuer}|{settings.client_id}")
        self._metadata: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self._pending: PendingLogin | None = None

    # ── discovery & token endpoint ──

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            url = f"{self.settings.issuer}/.well-known/openid-configuration"
            try:
                r = await self._http.get(url)
            except httpx2.HTTPError as e:
                raise SsoError(f"Could not reach the SSO provider at {url}: {e}") from e
            if r.status_code != 200:
                raise SsoError(f"OIDC discovery failed at {url}: HTTP {r.status_code}. Check UNIZO_CTEM_OIDC_ISSUER.")
            self._metadata = r.json()
        return self._metadata

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        meta = await self._discover()
        form = {**form, "client_id": self.settings.client_id}
        if self.settings.client_secret:
            form["client_secret"] = self.settings.client_secret
        try:
            r = await self._http.post(meta["token_endpoint"], data=form)
        except httpx2.HTTPError as e:
            raise SsoError(f"Could not reach the SSO token endpoint: {e}") from e
        body = r.json() if "json" in r.headers.get("content-type", "") else {}
        if r.status_code != 200:
            reason = body.get("error_description") or body.get("error") or r.text[:300]
            raise SsoError(f"The SSO provider rejected the token request (HTTP {r.status_code}): {reason}")
        return body

    def _to_tokenset(self, body: dict[str, Any], previous: TokenSet | None = None) -> TokenSet:
        tokens = TokenSet(
            access_token=body.get("access_token", ""),
            id_token=body.get("id_token") or (previous.id_token if previous else ""),
            # Providers that don't rotate refresh tokens omit it on refresh; keep the old one.
            refresh_token=body.get("refresh_token") or (previous.refresh_token if previous else ""),
        )
        if self.settings.token_type == "id":
            tokens.expires_at = float(decode_jwt_claims(tokens.id_token).get("exp", 0))
        elif body.get("expires_in"):
            tokens.expires_at = self._clock() + float(body["expires_in"])
        if not self._bearer(tokens):
            raise SsoError(f"The SSO provider returned no {self.settings.token_type} token. Check UNIZO_CTEM_OIDC_SCOPES.")
        return tokens

    def _bearer(self, tokens: TokenSet) -> str:
        return tokens.id_token if self.settings.token_type == "id" else tokens.access_token

    def _fresh(self, tokens: TokenSet) -> bool:
        return not tokens.expires_at or tokens.expires_at - EXPIRY_SKEW_SECONDS > self._clock()

    # ── public API ──

    async def bearer_token(self, force_refresh: bool = False) -> str | None:
        """A valid token for the gateway, refreshing if needed. ``None`` means the user must log in."""
        async with self._lock:
            tokens = self._store.load()
            if tokens is None:
                return None
            if not force_refresh and self._fresh(tokens):
                return self._bearer(tokens)
            if not tokens.refresh_token:
                return None
            try:
                body = await self._token_request(
                    {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
                )
            except SsoError:
                # Refresh token expired or revoked: forget it so the next step is a clean login.
                self._store.delete()
                return None
            tokens = self._to_tokenset(body, previous=tokens)
            self._store.save(tokens)
            return self._bearer(tokens)

    async def begin_login(self) -> PendingLogin:
        """Starts the callback listener and returns the URL the user must open. Reuses an in-flight login."""
        if self._pending and not self._pending.done.done():
            return self._pending
        meta = await self._discover()
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": self.settings.scopes,
            "state": state,
            "nonce": secrets.token_urlsafe(24),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.settings.audience:
            params["audience"] = self.settings.audience
        url = f"{meta['authorization_endpoint']}?{urlencode(params)}"

        loop = asyncio.get_running_loop()
        code_future: asyncio.Future[str] = loop.create_future()
        server = await self._start_callback_server(state, code_future)

        async def finish() -> TokenSet:
            try:
                code = await code_future
            finally:
                server.close()
            body = await self._token_request(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "code_verifier": verifier,
                }
            )
            tokens = self._to_tokenset(body)
            async with self._lock:
                self._store.save(tokens)
            return tokens

        task = asyncio.ensure_future(finish())
        # Give up on the listener after 10 minutes so a forgotten login doesn't hold the port forever.
        loop.call_later(600, lambda: code_future.done() or code_future.set_exception(SsoError("Login timed out.")))
        self._pending = PendingLogin(url=url, done=task)
        return self._pending

    async def login(self, wait_seconds: float = 120.0, open_browser: bool = True) -> tuple[str, TokenSet | None]:
        """Begins a login, opens the browser, and waits up to ``wait_seconds``.

        Returns ``(url, tokens)``; ``tokens`` is ``None`` if the user hasn't finished yet (the listener keeps
        running, so they can still complete it in the browser)."""
        pending = await self.begin_login()
        if open_browser:
            # In a thread, fire-and-forget: webbrowser.open can block until the browser command exits (BROWSER=...,
            # some xdg-open setups), and blocking here would stop the event loop from serving the very callback
            # the browser is about to hit.
            asyncio.get_running_loop().run_in_executor(None, self._try_open_browser, pending.url)
        try:
            tokens = await asyncio.wait_for(asyncio.shield(pending.done), timeout=wait_seconds)
        except TimeoutError:
            return pending.url, None
        return pending.url, tokens

    def _try_open_browser(self, url: str) -> None:
        try:
            self._open_browser(url)
        except Exception:  # noqa: BLE001, S110 - no browser is fine; the URL is returned to the user
            pass

    def logout(self) -> None:
        self._store.delete()

    def identity(self) -> dict[str, Any]:
        """Who is logged in, from the cached id_token (unverified, display only)."""
        tokens = self._store.load()
        if tokens is None:
            return {"logged_in": False}
        claims = decode_jwt_claims(tokens.id_token)
        info: dict[str, Any] = {
            "logged_in": True,
            "subject": claims.get("email") or claims.get("preferred_username") or claims.get("sub"),
            "token_expired": not self._fresh(tokens),
            "can_refresh": bool(tokens.refresh_token),
        }
        if tokens.expires_at:
            info["expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tokens.expires_at))
        return info

    async def aclose(self) -> None:
        if self._pending and not self._pending.done.done():
            self._pending.done.cancel()
        await self._http.aclose()

    # ── loopback callback listener ──

    async def _start_callback_server(self, state: str, code_future: asyncio.Future[str]) -> asyncio.Server:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request_line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
                while (await asyncio.wait_for(reader.readline(), 10)) not in (b"\r\n", b"\n", b""):
                    pass
                parts = request_line.split()
                target = urlsplit(parts[1]) if len(parts) >= 2 else urlsplit("/")
                if target.path != "/callback":
                    await _respond(writer, 404, "Not found.")
                    return
                query = {k: v[0] for k, v in parse_qs(target.query).items()}
                if query.get("state") != state:
                    await _respond(writer, 400, "Login failed: state mismatch. Start the login again.")
                    return
                if "error" in query:
                    message = query.get("error_description") or query["error"]
                    if not code_future.done():
                        code_future.set_exception(SsoError(f"The SSO provider returned an error: {message}"))
                    await _respond(writer, 400, f"Login failed: {message}")
                    return
                if not query.get("code"):
                    await _respond(writer, 400, "Login failed: no authorization code.")
                    return
                if not code_future.done():
                    code_future.set_result(query["code"])
                await _respond(writer, 200, "Logged in to Unizo CTEM. You can close this tab and return to Claude.")
            except (TimeoutError, ConnectionError):
                pass
            finally:
                writer.close()

        try:
            return await asyncio.start_server(handle, "127.0.0.1", self.settings.redirect_port)
        except OSError as e:
            raise SsoError(
                f"Could not listen on localhost:{self.settings.redirect_port} for the SSO callback ({e}). "
                "Close whatever is using it or set UNIZO_CTEM_OIDC_REDIRECT_PORT (and register the new redirect URI)."
            ) from e


async def _respond(writer: asyncio.StreamWriter, status: int, message: str) -> None:
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}[status]
    body = f"<!doctype html><meta charset=utf-8><title>Unizo CTEM</title><p>{html.escape(message)}</p>".encode()
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    await writer.drain()
