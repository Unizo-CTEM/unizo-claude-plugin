"""Settings come from the plugin's userConfig via env vars; bad values must not crash the server."""

from __future__ import annotations

import pytest

from unizo_mcp.config import Settings

KEYS = [
    "UNIZO_API_URL", "UNIZO_API_TOKEN", "UNIZO_OIDC_ISSUER", "UNIZO_OIDC_CLIENT_ID", "UNIZO_OIDC_CLIENT_SECRET",
    "UNIZO_OIDC_SCOPES", "UNIZO_OIDC_AUDIENCE", "UNIZO_OIDC_TOKEN_TYPE", "UNIZO_OIDC_REDIRECT_PORT",
    "UNIZO_API_TIMEOUT", "UNIZO_TOKEN_CACHE", "UNIZO_CONFIGURE_HINT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_empty_plugin_options_mean_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset optional userConfig values arrive as empty strings.
    for k in KEYS:
        monkeypatch.setenv(k, "")
    s = Settings.from_env()
    assert s.auth_mode == "none" and not s.configured and s.problems == ()
    assert s.oidc.scopes == "openid profile email offline_access"
    assert s.oidc.token_type == "access" and s.oidc.redirect_port == 8765


def test_sso_settings_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIZO_API_URL", "https://unizo.acme.com/")
    monkeypatch.setenv("UNIZO_OIDC_ISSUER", "https://acme.okta.com/oauth2/default/")
    monkeypatch.setenv("UNIZO_OIDC_CLIENT_ID", "0oa123")
    monkeypatch.setenv("UNIZO_OIDC_REDIRECT_PORT", "9123")
    monkeypatch.setenv("UNIZO_OIDC_TOKEN_TYPE", "ID")
    monkeypatch.setenv("UNIZO_CONFIGURE_HINT", "Run /unizo:unizo-plugin-configure")
    s = Settings.from_env()
    assert s.api_url == "https://unizo.acme.com" and s.auth_mode == "sso"
    assert s.oidc.issuer == "https://acme.okta.com/oauth2/default"
    assert s.oidc.redirect_uri == "http://localhost:9123/callback" and s.oidc.token_type == "id"
    assert s.configure_hint == "Run /unizo:unizo-plugin-configure"


def test_bad_values_are_reported_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIZO_OIDC_TOKEN_TYPE", "jwt")
    monkeypatch.setenv("UNIZO_OIDC_REDIRECT_PORT", "eighty")
    monkeypatch.setenv("UNIZO_OIDC_ISSUER", "https://acme.okta.com")
    s = Settings.from_env()
    assert s.oidc.token_type == "access" and s.oidc.redirect_port == 8765 and s.auth_mode == "none"
    assert len(s.problems) == 3
