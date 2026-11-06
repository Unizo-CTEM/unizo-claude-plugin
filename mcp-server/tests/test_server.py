"""Runs the real server in-process through an MCP client session, with the CTEM gateway mocked."""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp import Client

from unizo_ctem_mcp.client import UnizoCtemClient
from unizo_ctem_mcp.config import Settings
from unizo_ctem_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def gateway(status: int, seen: list[httpx2.Request] | None = None) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(status, json={"status": "UP"})

    return httpx2.MockTransport(handle)


async def call_status(settings: Settings, transport: httpx2.MockTransport) -> dict:
    server = build_server(settings, UnizoCtemClient(settings, transport=transport))
    async with Client(server) as client:
        result = await client.call_tool("unizo_ctem_status", {})
        assert not result.is_error, result
        return json.loads(result.content[0].text)


async def test_lists_status_tool() -> None:
    server = build_server(Settings(api_url="", api_token=""))
    async with Client(server) as client:
        tools = await client.list_tools()
    assert "unizo_ctem_status" in [t.name for t in tools.tools]


async def test_status_reports_missing_configuration() -> None:
    status = await call_status(Settings(api_url="", api_token=""), gateway(200))
    assert status["reachable"] is False
    assert "API URL is not configured" in status["detail"]


async def test_status_checks_health_with_bearer_token() -> None:
    seen: list[httpx2.Request] = []
    status = await call_status(Settings(api_url="https://ctem.example", api_token="t0k"), gateway(200, seen))
    assert status == {
        "server_version": "0.1.0",
        "api_url": "https://ctem.example",
        "token_configured": True,
        "auth_mode": "static-token",
        "environment": None,
        "reachable": True,
    }
    assert seen[0].url.path == "/health"
    assert seen[0].headers["Authorization"] == "Bearer t0k"


async def test_status_explains_auth_failure() -> None:
    status = await call_status(Settings(api_url="https://ctem.example", api_token="bad"), gateway(401))
    assert status["reachable"] is False
    assert "API token" in status["detail"]
