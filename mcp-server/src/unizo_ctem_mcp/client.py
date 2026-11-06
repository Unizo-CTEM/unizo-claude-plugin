"""Thin async HTTP client for the CTEM web gateway. Every tool that calls the platform goes through here."""

from __future__ import annotations

from typing import Any

import httpx2

from unizo_ctem_mcp.auth import OidcAuth, SsoError
from unizo_ctem_mcp.config import Settings


class UnizoCtemApiError(Exception):
    """A failure worth showing to the model as-is: it explains what went wrong and what to do."""


class UnizoCtemClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx2.AsyncBaseTransport | None = None,
        auth: OidcAuth | None = None,
    ) -> None:
        self._settings = settings
        self._auth = auth if settings.auth_mode == "sso" else None
        headers = {"Accept": "application/json", "User-Agent": "unizo-ctem-mcp"}
        if settings.api_token:
            headers["Authorization"] = f"Bearer {settings.api_token}"
        self._http = httpx2.AsyncClient(
            base_url=settings.api_url,
            headers=headers,
            timeout=settings.timeout_seconds,
            transport=transport,
        )

    async def _sso_headers(self, force_refresh: bool = False) -> dict[str, str]:
        if self._auth is None:
            return {}
        try:
            token = await self._auth.bearer_token(force_refresh=force_refresh)
        except SsoError as e:
            raise UnizoCtemApiError(str(e)) from e
        if token is None:
            raise UnizoCtemApiError("Not logged in to CTEM SSO. Call the unizo_ctem_login tool (or run `unizo-ctem-mcp login`).")
        return {"Authorization": f"Bearer {token}"}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a JSON endpoint relative to UNIZO_CTEM_API_URL, e.g. ``await client.get("/health")``."""
        if not self._settings.configured:
            raise UnizoCtemApiError(f"The CTEM API URL is not configured. {self._settings.configure_hint}.")
        response = await self._send(path, params, await self._sso_headers())
        if response.status_code == 401 and self._auth is not None:
            # The gateway may reject a token we thought was still valid (clock skew, revocation): refresh once.
            response = await self._send(path, params, await self._sso_headers(force_refresh=True))
        if response.status_code in (401, 403):
            if self._auth:
                hint = "Call unizo_ctem_login to sign in again."
            else:
                hint = f"Check the API token or set up SSO. {self._settings.configure_hint}."
            raise UnizoCtemApiError(f"The CTEM API refused the request (HTTP {response.status_code}). {hint}")
        if response.status_code >= 400:
            raise UnizoCtemApiError(f"GET {path} failed: HTTP {response.status_code} {response.text[:500]}")
        if not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    async def _send(self, path: str, params: dict[str, Any] | None, headers: dict[str, str]) -> httpx2.Response:
        try:
            return await self._http.get(path, params=params, headers=headers)
        except httpx2.HTTPError as e:
            raise UnizoCtemApiError(f"Could not reach {self._settings.api_url}{path}: {e}") from e

    async def aclose(self) -> None:
        await self._http.aclose()
