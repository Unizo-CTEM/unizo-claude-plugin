"""Named CTEM environments (demo, staging, prod, ...) and switching between them.

An environments file lists, per environment, the gateway/SSO settings for the local ``unizo-ctem`` server and the remote
MCP server (URL and OAuth client ID). ``unizo-ctem-mcp env use <name>`` makes one active:

* the local ``unizo-ctem`` server reads the active environment at startup (see ``Settings.from_env``), so nothing is
  written to the plugin options. Claude Code can't clear a plugin option, so rewriting them would leak one
  environment's values into the next.
* the remote server is registered at user scope as ``unizo-ctem-cloud`` with ``claude mcp add-json``, because Claude Code
  doesn't substitute plugin options or environment variables into ``oauth.clientId``.

Files, later ones overriding earlier ones by environment name:

1. ``<plugin root>/environments.json``, shipped with the plugin
2. ``$UNIZO_CTEM_ENVIRONMENTS_FILE``, or else ``~/.config/unizo-ctem-mcp/environments.json``

Any other file can be named with ``--file <path>`` (``env list --file <path>``, ``env use <name> --file <path>``).
The active environment remembers the file it came from, so that file keeps working after the switch.

Secrets never go in these files: ``api_token`` and ``sso_client_secret`` stay in ``/plugin configure``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REMOTE_SERVER_NAME = "unizo-ctem-cloud"

# Environment key -> the variable the server reads (the same names the plugin's .mcp.json sets).
SETTING_VARS = {
    "api_url": "UNIZO_CTEM_API_URL",
    "sso_issuer": "UNIZO_CTEM_OIDC_ISSUER",
    "sso_client_id": "UNIZO_CTEM_OIDC_CLIENT_ID",
    "sso_scopes": "UNIZO_CTEM_OIDC_SCOPES",
    "sso_audience": "UNIZO_CTEM_OIDC_AUDIENCE",
    "sso_token_type": "UNIZO_CTEM_OIDC_TOKEN_TYPE",
    "sso_redirect_port": "UNIZO_CTEM_OIDC_REDIRECT_PORT",
}
SECRET_VARS = {"api_token": "UNIZO_CTEM_API_TOKEN", "sso_client_secret": "UNIZO_CTEM_OIDC_CLIENT_SECRET"}
OTHER_KEYS = {"description", "remote_mcp", "use_plugin_secrets"}
REMOTE_KEYS = {"url", "client_id", "callback_port", "scopes"}


class EnvConfigError(Exception):
    """A problem with an environments file or the active environment, worded for the user."""


@dataclass(frozen=True)
class RemoteMcp:
    url: str
    client_id: str = ""
    callback_port: int | None = None
    scopes: str = ""

    def server_config(self) -> dict[str, Any]:
        """The JSON for ``claude mcp add-json``."""
        oauth: dict[str, Any] = {}
        if self.client_id:
            oauth["clientId"] = self.client_id
        if self.callback_port:
            oauth["callbackPort"] = self.callback_port
        if self.scopes:
            oauth["scopes"] = self.scopes
        config: dict[str, Any] = {"type": "http", "url": self.url}
        if oauth:
            config["oauth"] = oauth
        return config


@dataclass(frozen=True)
class Environment:
    name: str
    source: Path
    description: str = ""
    settings: Mapping[str, str] = field(default_factory=dict)
    """Values keyed like the plugin options (``api_url``, ``sso_issuer``, ...)."""
    remote: RemoteMcp | None = None
    use_plugin_secrets: bool = False
    """If true, ``api_token`` / ``sso_client_secret`` from ``/plugin configure`` are used with this environment.
    Off by default, so a token set for one deployment is never sent to another."""

    def apply_to(self, env: Mapping[str, str]) -> dict[str, str]:
        """Returns ``env`` with this environment's settings in place of the plugin options.

        Every setting the environment leaves out falls back to the server default, not to the plugin option, so
        nothing carries over from whatever was configured before."""
        out = dict(env)
        for key, var in SETTING_VARS.items():
            out[var] = self.settings.get(key, "")
        if not self.use_plugin_secrets:
            for var in SECRET_VARS.values():
                out[var] = ""
        return out


# ── Locations ─────────────────────────────────────────────────────────────────────────────────────────────────


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-ctem-mcp"


def plugin_root() -> Path:
    root = os.environ.get("UNIZO_CTEM_PLUGIN_ROOT", "").strip() or os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[3]  # <root>/mcp-server/src/unizo_ctem_mcp/environments.py


def user_file() -> Path:
    custom = os.environ.get("UNIZO_CTEM_ENVIRONMENTS_FILE", "").strip()
    return Path(custom).expanduser() if custom else config_dir() / "environments.json"


def environment_files() -> list[Path]:
    return [plugin_root() / "environments.json", user_file()]


def resolve_file(path: str | Path) -> Path:
    """An environments file named by the user, as an absolute path (the state outlives the current directory)."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise EnvConfigError(f"Environments file not found: {resolved}")
    return resolved


def state_file() -> Path:
    return config_dir() / "active-environment.json"


# ── Loading ───────────────────────────────────────────────────────────────────────────────────────────────────


def parse_file(path: Path) -> dict[str, Environment]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise EnvConfigError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("environments"), dict):
        raise EnvConfigError(f'{path} must be a JSON object with an "environments" object.')
    return {name: _parse_environment(name, raw, path) for name, raw in data["environments"].items()}


def _parse_environment(name: str, raw: Any, path: Path) -> Environment:
    where = f'{path}: environment "{name}"'
    if not name or not all(c.isalnum() or c in "-_." for c in name):
        raise EnvConfigError(f"{where}: names may use only letters, digits, '-', '_' and '.'.")
    if not isinstance(raw, dict):
        raise EnvConfigError(f"{where} must be a JSON object.")
    secrets = sorted(set(raw) & set(SECRET_VARS))
    if secrets:
        raise EnvConfigError(
            f"{where} contains {', '.join(secrets)}. Secrets don't belong in this file: set them with "
            '/plugin configure unizo-ctem@unizo-ctem and add "use_plugin_secrets": true to the environment.'
        )
    unknown = sorted(set(raw) - set(SETTING_VARS) - OTHER_KEYS)
    if unknown:
        known = ", ".join([*SETTING_VARS, *sorted(OTHER_KEYS)])
        raise EnvConfigError(f"{where}: unknown key(s) {', '.join(unknown)}. Known keys: {known}.")

    settings: dict[str, str] = {}
    for key in SETTING_VARS:
        if key in raw and raw[key] is not None:
            value = raw[key]
            if not isinstance(value, str | int) or isinstance(value, bool):
                raise EnvConfigError(f"{where}: {key} must be a string.")
            settings[key] = str(value).strip()

    remote = None
    if raw.get("remote_mcp") is not None:
        remote = _parse_remote(raw["remote_mcp"], where)

    use_secrets = raw.get("use_plugin_secrets", False)
    if not isinstance(use_secrets, bool):
        raise EnvConfigError(f"{where}: use_plugin_secrets must be true or false.")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise EnvConfigError(f"{where}: description must be a string.")
    return Environment(name, path, description, settings, remote, use_secrets)


def _parse_remote(raw: Any, where: str) -> RemoteMcp:
    where = f"{where}: remote_mcp"
    if not isinstance(raw, dict):
        raise EnvConfigError(f"{where} must be a JSON object with a url.")
    unknown = sorted(set(raw) - REMOTE_KEYS)
    if unknown:
        raise EnvConfigError(f"{where}: unknown key(s) {', '.join(unknown)}. Known keys: {', '.join(sorted(REMOTE_KEYS))}.")
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise EnvConfigError(f"{where}: url is required.")
    url = url.strip()
    local = url.startswith(("http://localhost", "http://127.0.0.1"))
    if not (url.startswith("https://") or local):
        raise EnvConfigError(f"{where}: url must start with https:// (http:// is allowed only for localhost).")
    client_id = raw.get("client_id") or ""
    scopes = raw.get("scopes") or ""
    if not isinstance(client_id, str) or not isinstance(scopes, str):
        raise EnvConfigError(f"{where}: client_id and scopes must be strings.")
    port = raw.get("callback_port")
    if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535):
        raise EnvConfigError(f"{where}: callback_port must be a whole number from 1 to 65535.")
    return RemoteMcp(url, client_id.strip(), port, scopes.strip())


def load_environments(files: list[Path] | None = None) -> dict[str, Environment]:
    """All environments from the files that exist; a later file replaces an earlier one's entry of the same name."""
    found: dict[str, Environment] = {}
    for path in files if files is not None else environment_files():
        if path.is_file():
            found.update(parse_file(path))
    return found


def read_state() -> dict[str, Any] | None:
    path = state_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("name"), str) else None


def active_environment() -> Environment | None:
    """The environment chosen with ``unizo-ctem-mcp env use``, or None. Raises EnvConfigError if it's broken."""
    state = read_state()
    if state is None:
        return None
    name = state["name"]
    source = Path(state["source"]) if isinstance(state.get("source"), str) else None
    if source is not None and source.is_file():
        from_source = parse_file(source)
        if name in from_source:
            return from_source[name]
    envs = load_environments()
    if name not in envs:
        raise EnvConfigError(
            f'The active CTEM environment "{name}" is no longer in any environments file. '
            "Run /unizo-ctem:unizo-ctem-env to pick another."
        )
    return envs[name]


def _write_state(data: dict[str, Any] | None) -> None:
    path = state_file()
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".active-environment.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ── Switching ─────────────────────────────────────────────────────────────────────────────────────────────────

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def _remote_registered(run: Runner) -> bool:
    """Whether a user-scope ``unizo-ctem-cloud`` server exists."""
    result = run(["claude", "mcp", "get", REMOTE_SERVER_NAME])
    return result.returncode == 0 and "Scope: User" in result.stdout


def use(
    name: str,
    *,
    file: Path | None = None,
    force: bool = False,
    run: Runner = _run,
    out: Callable[[str], None] = print,
) -> Environment:
    """Makes ``name`` the active environment and registers its remote MCP server.

    With ``file``, ``name`` is looked up in that file only; otherwise in the default environments files."""
    envs = parse_file(file) if file is not None else load_environments()
    if name not in envs:
        where = f" in {file}" if file is not None else ""
        available = ", ".join(sorted(envs)) or "none (no environments file found)"
        available = f"{available}{where}"
        raise EnvConfigError(f'No environment named "{name}". Available: {available}.')
    env = envs[name]
    state = read_state()
    owned = bool(state and state.get("remote_registered"))
    exists = _remote_registered(run)
    if exists and not owned and not force:
        raise EnvConfigError(
            f'A user-scope MCP server named "{REMOTE_SERVER_NAME}" already exists and wasn\'t added by this '
            "command. Remove it (claude mcp remove --scope user unizo-ctem-cloud) or run again with --force to replace it."
        )

    previous_remote = (state or {}).get("remote")
    new_remote = env.remote.server_config() if env.remote else None
    if exists:
        if previous_remote != new_remote:
            # Claude Code keeps a server's OAuth client registration and tokens by name, and a cached registration
            # wins over a changed clientId. Sign out so the next sign-in uses this environment's client.
            run(["claude", "mcp", "logout", REMOTE_SERVER_NAME])
        removed = run(["claude", "mcp", "remove", "--scope", "user", REMOTE_SERVER_NAME])
        if removed.returncode != 0:
            raise EnvConfigError(f"Couldn't remove the old {REMOTE_SERVER_NAME} server: {_detail(removed)}")
    if new_remote is not None:
        added = run(["claude", "mcp", "add-json", "--scope", "user", REMOTE_SERVER_NAME, json.dumps(new_remote)])
        if added.returncode != 0:
            raise EnvConfigError(f"Couldn't register the remote MCP server: {_detail(added)}")

    _write_state(
        {
            "name": env.name,
            "source": str(env.source),
            "remote": new_remote,
            "remote_registered": new_remote is not None,
            "activated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    out(f'Active CTEM environment: {env.name}{f" ({env.description})" if env.description else ""}')
    out(f"  gateway:    {env.settings.get('api_url') or '(not set)'}")
    out(f"  sso issuer: {env.settings.get('sso_issuer') or '(not set)'}")
    if env.remote:
        cid = env.remote.client_id or "(dynamic client registration)"
        out(f"  remote MCP: {env.remote.url}  client ID: {cid}")
    else:
        out("  remote MCP: none")
    out("Restart Claude Code to apply. Then sign in: /unizo-ctem:unizo-ctem-setup for the gateway, /mcp -> unizo-ctem-cloud for the "
        "remote server.")
    return env


def off(*, run: Runner = _run, out: Callable[[str], None] = print) -> None:
    """Deactivates environments: the plugin options apply again, and the remote server this command added is removed."""
    state = read_state()
    if state is None:
        out("No CTEM environment is active; the plugin options from /plugin configure apply.")
        return
    if state.get("remote_registered") and _remote_registered(run):
        run(["claude", "mcp", "logout", REMOTE_SERVER_NAME])
        run(["claude", "mcp", "remove", "--scope", "user", REMOTE_SERVER_NAME])
    _write_state(None)
    out(f'Deactivated environment "{state["name"]}". The plugin options from /plugin configure apply again.')
    out("Restart Claude Code to apply.")


def mark_setup_complete(*, out: Callable[[str], None] = print) -> None:
    """Records that /unizo-ctem:unizo-ctem-setup finished for the active environment, so the onboarding hook goes quiet.

    Switching environments rewrites the state without this flag, so the next environment is set up again."""
    state = read_state()
    if state is None:
        raise EnvConfigError("No CTEM environment is active. Run /unizo-ctem:unizo-ctem-setup to pick one first.")
    state["setup_complete"] = True
    state["setup_completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_state(state)
    out(f'Setup recorded as complete for environment "{state["name"]}".')


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"


# ── CLI: unizo-ctem-mcp env ... ─────────────────────────────────────────────────────────────────────────────────────

USAGE = """usage: unizo-ctem-mcp env [list [--file <path>] | current | use <name> [--file <path>] [--force] | off | setup-done]

  list           environments from the environments files (* marks the active one)
  --file <path>  read environments from <path> only, instead of the default files
  current        the active environment and where it's defined
  use <name>     make <name> active and register its remote MCP server as unizo-ctem-cloud
  off            go back to the plugin options; remove the unizo-ctem-cloud server this command added
  setup-done     record that /unizo-ctem:unizo-ctem-setup finished for the active environment

Files: {files}"""


def _pop_file(args: list[str]) -> tuple[list[str], Path | None]:
    """Removes ``--file <path>`` / ``-f <path>`` / ``--file=<path>`` from ``args``."""
    rest: list[str] = []
    file: Path | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--file", "-f"):
            if i + 1 >= len(args):
                raise EnvConfigError(f"{arg} needs a path to an environments file.")
            file = resolve_file(args[i + 1])
            i += 2
            continue
        if arg.startswith("--file="):
            file = resolve_file(arg.split("=", 1)[1])
        else:
            rest.append(arg)
        i += 1
    return rest, file


def cli(args: list[str]) -> int:
    try:
        args, file = _pop_file(args)
        command = args[0] if args else "list"
        if command == "list":
            envs = parse_file(file) if file is not None else load_environments()
            state = read_state() or {}
            active = state.get("name")
            if file is not None and state.get("source") != str(file):
                active = None
            if not envs:
                where = str(file) if file is not None else f"Create {user_file()} (see environments.example.json)."
                print(f"No environments found. {where}")
                return 1
            for name in sorted(envs):
                env = envs[name]
                mark = "*" if name == active else " "
                desc = f"  {env.description}" if env.description else ""
                print(f"{mark} {name:<14}{env.settings.get('api_url', ''):<36}{desc}")
            return 0
        if command == "current":
            state = read_state()
            if state is None:
                print("No CTEM environment is active; the plugin options from /plugin configure apply.")
                return 0
            env = active_environment()
            assert env is not None
            print(f"{env.name}  (from {env.source}, since {state.get('activated_at', '?')})")
            for key in SETTING_VARS:
                if key in env.settings:
                    print(f"  {key}: {env.settings[key]}")
            print(f"  remote_mcp: {json.dumps(state.get('remote'))}")
            return 0
        if command == "use" and len(args) >= 2:
            use(args[1], file=file, force="--force" in args[2:])
            return 0
        if command == "off":
            off()
            return 0
        if command == "setup-done":
            mark_setup_complete()
            return 0
        print(USAGE.format(files=", ".join(str(p) for p in environment_files())), file=sys.stderr)
        return 2
    except EnvConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e.filename or 'claude'} not found. The Claude Code CLI must be on PATH.", file=sys.stderr)
        return 1
