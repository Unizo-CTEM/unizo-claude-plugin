"""The Unizo MCP server. Claude Code starts it over stdio (see the plugin's .mcp.json).

Add tools here with ``@mcp.tool()``. The function's docstring becomes the tool description the model reads, and
its type hints become the input schema, so write both for the model. Raise ``UnizoApiError`` for failures the model
should see and recover from. Never print to stdout: stdout carries the MCP protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from unizo_mcp import __version__
from unizo_mcp.auth import OidcAuth, SsoError
from unizo_mcp.client import UnizoApiError, UnizoClient
from unizo_mcp.config import Settings

# The HTTP client logs every request at INFO; that's noise in Claude Code's MCP logs.
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore2").setLevel(logging.WARNING)


@dataclass
class AppState:
    settings: Settings
    client: UnizoClient
    auth: OidcAuth | None


def build_server(
    settings: Settings | None = None, client: UnizoClient | None = None, auth: OidcAuth | None = None
) -> MCPServer:
    """Builds the server. Tests pass their own settings/client/auth; production reads the environment."""

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[AppState]:
        resolved = settings or Settings.from_env()
        sso = auth
        if sso is None and resolved.auth_mode == "sso":
            assert resolved.oidc is not None
            sso = OidcAuth(resolved.oidc)
        http = client or UnizoClient(resolved, auth=sso)
        try:
            yield AppState(settings=resolved, client=http, auth=sso)
        finally:
            await http.aclose()
            if sso is not None:
                await sso.aclose()

    mcp = MCPServer(
        name="unizo",
        version=__version__,
        instructions=(
            "Tools for the Unizo platform. "
            "If a tool reports that the server is not configured, relay its configuration hint to the user "
            "instead of retrying. "
            "If a tool says the user is not logged in to SSO, call unizo_login once and give the user the "
            "login URL it returns; don't call it in a loop."
        ),
        lifespan=lifespan,
    )

    def state(ctx: Context) -> AppState:
        return ctx.request_context.lifespan_context

    @mcp.tool()
    async def unizo_status(ctx: Context) -> dict[str, Any]:
        """Check the Unizo connection: which API URL is configured, whether a token is set, and whether the
        gateway's /health endpoint answers. Use this first when other Unizo tools fail."""
        s = state(ctx)
        result: dict[str, Any] = {
            "server_version": __version__,
            "api_url": s.settings.api_url or None,
            "token_configured": bool(s.settings.api_token),
            "auth_mode": s.settings.auth_mode,
            "environment": s.settings.environment or None,
        }
        if s.settings.environment:
            result["environment_source"] = s.settings.environment_source
        if s.settings.problems:
            result["config_problems"] = list(s.settings.problems)
        if not s.settings.configured:
            result["reachable"] = False
            result["detail"] = f"The Unizo API URL is not configured. {s.settings.configure_hint}."
        else:
            try:
                await s.client.get("/health")
                result["reachable"] = True
            except UnizoApiError as e:
                result["reachable"] = False
                result["detail"] = str(e)
        if s.auth is not None:
            # After the health check: it may have refreshed the token or cleared a revoked session.
            result["sso"] = {"issuer": s.auth.settings.issuer, **s.auth.identity()}
        return result

    @mcp.tool()
    async def unizo_login(ctx: Context, wait_seconds: int = 90) -> dict[str, Any]:
        """Sign the user in to Unizo through their company SSO. Opens the SSO login page in the user's
        browser and waits up to ``wait_seconds`` (max 300) for them to finish. If it returns ``logged_in: false``
        with a ``login_url``, show the URL to the user and ask them to complete the login there; the login stays
        open for 10 minutes, so afterwards just retry the original request. Only needed when SSO is configured."""
        s = state(ctx)
        if s.auth is None:
            if s.settings.api_token:
                return {"logged_in": True, "detail": "Using the static UNIZO_API_TOKEN; no SSO login needed."}
            return {
                "logged_in": False,
                "detail": f"SSO is not configured (needs the SSO issuer URL and client ID). {s.settings.configure_hint}.",
            }
        try:
            url, tokens = await s.auth.login(wait_seconds=max(1, min(wait_seconds, 300)))
        except SsoError as e:
            raise UnizoApiError(str(e)) from e
        if tokens is None:
            return {
                "logged_in": False,
                "login_url": url,
                "detail": "Waiting for the user to finish signing in. Ask them to open login_url in a browser.",
            }
        return s.auth.identity()

    @mcp.tool()
    async def unizo_logout(ctx: Context) -> dict[str, Any]:
        """Sign out of Unizo SSO by deleting the locally cached tokens. Use only when the user asks to sign out or
        to switch accounts."""
        s = state(ctx)
        if s.auth is None:
            return {"logged_in": False, "detail": "SSO is not configured."}
        s.auth.logout()
        return {"logged_in": False, "detail": "Cached Unizo SSO tokens deleted."}

    # ── Add Unizo tools below. Template (replace the path with a real gateway route): ──
    #
    # @mcp.tool()
    # async def get_exposure(exposure_id: str, ctx: Context) -> dict[str, Any]:
    #     """Fetch one exposure by id, including its assets, severity and current status."""
    #     return await state(ctx).client.get(f"/api/<service>/exposures/{exposure_id}")

    return mcp


async def _cli(command: str) -> int:
    """Terminal helpers that share the server's token cache: ``unizo-mcp login | logout | whoami``."""
    settings = Settings.from_env()
    if settings.oidc is None or not settings.oidc.enabled:
        print("SSO is not configured: set UNIZO_OIDC_ISSUER and UNIZO_OIDC_CLIENT_ID.", file=sys.stderr)
        return 2
    auth = OidcAuth(settings.oidc)
    try:
        if command == "login":
            pending = await auth.begin_login()
            print(f"Opening your browser to sign in. If it doesn't open, visit:\n\n  {pending.url}\n")
            _, tokens = await auth.login(wait_seconds=600)
            if tokens is None:
                print("Timed out waiting for the login.", file=sys.stderr)
                return 1
            print(f"Logged in as {auth.identity().get('subject') or 'unknown user'}.")
        elif command == "logout":
            auth.logout()
            print("Logged out; cached tokens deleted.")
        else:
            print(auth.identity())
        return 0
    except SsoError as e:
        print(f"SSO error: {e}", file=sys.stderr)
        return 1
    finally:
        await auth.aclose()


async def _headers() -> dict[str, str]:
    """The ``Authorization`` header for the remote ``unizo-cloud`` server, from the gateway's SSO token cache.

    Claude Code runs ``unizo-mcp headers`` as that server's ``headersHelper``, so one SSO sign-in covers both
    servers. Not signed in, SSO not configured, or any error: no headers, and Claude Code falls back to its own
    OAuth sign-in for the server."""
    settings = Settings.from_env()
    if settings.oidc is None or not settings.oidc.enabled:
        return {}
    auth = OidcAuth(settings.oidc)
    try:
        token = await asyncio.wait_for(auth.bearer_token(), timeout=8)
    except Exception:  # noqa: BLE001 - a helper failure must not break the server connection
        return {}
    finally:
        await auth.aclose()
    return {"Authorization": f"Bearer {token}"} if token else {}


def main() -> None:
    args = sys.argv[1:]
    if args == ["headers"]:
        try:
            headers = asyncio.run(_headers())
        except Exception:  # noqa: BLE001
            headers = {}
        print(json.dumps(headers))
        raise SystemExit(0)
    if args and args[0] == "env":
        from unizo_mcp.environments import cli

        raise SystemExit(cli(args[1:]))
    if args and args[0] in ("login", "logout", "whoami"):
        raise SystemExit(asyncio.run(_cli(args[0])))
    if args:
        print(
            "usage: unizo-mcp [login | logout | whoami | headers | env ...]   (no arguments: run the MCP server on stdio)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
