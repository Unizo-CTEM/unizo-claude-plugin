"""Tests for ``unizo-ctem-mcp headers``, the remote server's headersHelper (one SSO sign-in for both servers)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from unizo_ctem_mcp.auth import TokenSet, TokenStore

ISSUER = "https://login.example.com"
CLIENT = "ctem-client"


def run_headers(config_home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIZO_CTEM_")}
    env.update(XDG_CONFIG_HOME=str(config_home), UNIZO_CTEM_OIDC_ISSUER=ISSUER, UNIZO_CTEM_OIDC_CLIENT_ID=CLIENT)
    proc = subprocess.run(
        [sys.executable, "-c", "from unizo_ctem_mcp.server import main; main()", "headers"],
        capture_output=True, text=True, env=env, check=True, timeout=30,
    )
    return json.loads(proc.stdout)


def test_not_signed_in_prints_no_headers(isolated_config: Path) -> None:
    assert run_headers(isolated_config / "config") == {}


def test_signed_in_prints_the_gateway_bearer_token(isolated_config: Path) -> None:
    cache = isolated_config / "config" / "unizo-ctem-mcp" / "tokens.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(cache, f"{ISSUER}|{CLIENT}").save(TokenSet(access_token="tok-1", expires_at=time.time() + 3600))
    assert run_headers(isolated_config / "config") == {"Authorization": "Bearer tok-1"}
