"""Settings, read from the active named environment or from ``UNIZO_CTEM_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_token_cache() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-ctem-mcp" / "tokens.json"


@dataclass(frozen=True)
class OidcSettings:
    """SSO login against an OAuth 2.0 / OIDC provider (Okta, Entra ID, Auth0, Google Workspace, ...)."""

    issuer: str
    """Issuer URL; ``{issuer}/.well-known/openid-configuration`` must exist. Empty means SSO is off."""

    client_id: str
    """Client ID of a *native/public* app registered with the IdP, with redirect URI
    ``http://localhost:{redirect_port}/callback``."""

    client_secret: str = ""
    """Only for IdPs that insist on a secret for native apps. Prefer a public client with PKCE."""

    scopes: str = "openid profile email offline_access"
    """``offline_access`` asks for a refresh token so the user doesn't log in every hour."""

    audience: str = ""
    """Sent as the ``audience`` parameter (Auth0 and some Okta setups need it to issue a JWT access token)."""

    token_type: str = "access"
    """Which token to send to the gateway: ``access`` (default) or ``id``."""

    redirect_port: int = 8765

    token_cache: Path = field(default_factory=_default_token_cache)

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id)

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.redirect_port}/callback"


@dataclass(frozen=True)
class Settings:
    api_url: str
    """Base URL of the CTEM web gateway, e.g. https://dev52.unizo.io. Empty means not configured."""

    api_token: str
    """Static bearer token. If set it wins over SSO, which is handy for CI and service accounts."""

    timeout_seconds: float = 20.0

    oidc: OidcSettings | None = None

    configure_hint: str = "Set the CTEM_* environment variables before starting Claude Code"
    """How the user fixes configuration. The plugin points this at ``/unizo-ctem:unizo-ctem-plugin-configure``."""

    problems: tuple[str, ...] = ()
    """Invalid settings that were replaced by defaults, reported by unizo_ctem_status instead of crashing."""

    environment: str = ""
    """The active named environment (``unizo-ctem-mcp env use``), or empty when the ``UNIZO_CTEM_*`` variables apply."""

    environment_source: str = ""
    """The environments file the active environment came from."""

    @property
    def configured(self) -> bool:
        return bool(self.api_url)

    @property
    def auth_mode(self) -> str:
        if self.api_token:
            return "static-token"
        if self.oidc and self.oidc.enabled:
            return "sso"
        return "none"

    @classmethod
    def from_env(cls) -> Settings:
        """Reads ``UNIZO_CTEM_*`` from the environment. If a named environment is active, its settings replace
        those variables (see ``environments.py``)."""
        from unizo_ctem_mcp import environments

        problems: list[str] = []
        values: dict[str, str] = dict(os.environ)
        active = None
        try:
            active = environments.active_environment()
        except environments.EnvConfigError as e:
            problems.append(f"{e} Using the UNIZO_CTEM_* environment variables instead.")
        if active is not None:
            values = active.apply_to(values)
        env = values.get
        token_type = env("UNIZO_CTEM_OIDC_TOKEN_TYPE", "").strip().lower() or "access"
        if token_type not in ("access", "id"):
            problems.append(f"SSO token type {token_type!r} is not 'access' or 'id'; using 'access'.")
            token_type = "access"
        port = _number(env("UNIZO_CTEM_OIDC_REDIRECT_PORT", ""), 8765, "SSO callback port", problems)
        timeout = _number(env("UNIZO_CTEM_API_TIMEOUT", ""), 20, "API timeout", problems)
        issuer = env("UNIZO_CTEM_OIDC_ISSUER", "").strip().rstrip("/")
        client_id = env("UNIZO_CTEM_OIDC_CLIENT_ID", "").strip()
        if bool(issuer) != bool(client_id):
            problems.append("SSO needs both the issuer URL and the client ID; SSO is off until both are set.")
        cache = env("UNIZO_CTEM_TOKEN_CACHE", "").strip()
        oidc = OidcSettings(
            issuer=issuer,
            client_id=client_id,
            client_secret=env("UNIZO_CTEM_OIDC_CLIENT_SECRET", "").strip(),
            scopes=env("UNIZO_CTEM_OIDC_SCOPES", "").strip() or "openid profile email offline_access",
            audience=env("UNIZO_CTEM_OIDC_AUDIENCE", "").strip(),
            token_type=token_type,
            redirect_port=int(port),
            token_cache=Path(cache).expanduser() if cache else _default_token_cache(),
        )
        return cls(
            api_url=env("UNIZO_CTEM_API_URL", "").strip().rstrip("/"),
            api_token=env("UNIZO_CTEM_API_TOKEN", "").strip(),
            timeout_seconds=float(timeout),
            oidc=oidc,
            configure_hint=env("UNIZO_CTEM_CONFIGURE_HINT", "").strip() or cls.configure_hint,
            problems=tuple(problems),
            environment=active.name if active else "",
            environment_source=str(active.source) if active else "",
        )


def _number(raw: str, default: float, label: str, problems: list[str]) -> float:
    raw = raw.strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        problems.append(f"{label} {raw!r} is not a number; using {default:g}.")
        return default
    if value <= 0:
        problems.append(f"{label} must be positive; using {default:g}.")
        return default
    return value
