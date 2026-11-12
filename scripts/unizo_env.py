#!/usr/bin/env python3
"""Switch between Unizo environments (demo, staging, prod, ...) by registering the remote MCP server.

An environments file lists, per environment, the remote Unizo MCP server (URL and, optionally, a pre-registered OAuth
client ID). ``use <name>`` registers that server at user scope as ``unizo-cloud`` with ``claude mcp add-json``
(Claude Code doesn't substitute environment variables into ``oauth.clientId``, so a plugin ``.mcp.json`` can't do
this). The user then signs in with Claude Code's own OAuth: ``/mcp`` -> ``unizo-cloud`` -> Authenticate.

There is no default environments file: the user always names one with ``--file <path>``. The active environment is
recorded in ``<config>/unizo-mcp/active-environment.json`` together with the file it came from; the onboarding hook
reads it.

Standard library only, Python 3.8+, so it runs with any ``python3`` and needs nothing installed.

    python3 unizo_env.py list --file <path>
    python3 unizo_env.py current
    python3 unizo_env.py use <name> --file <path> [--force]
    python3 unizo_env.py off
    python3 unizo_env.py setup-done
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REMOTE_SERVER_NAME = "unizo-cloud"
REMOTE_KEYS = {"url", "client_id", "callback_port", "scopes"}
SECRET_KEYS = {"api_token", "sso_client_secret"}
# Keys an environment may carry. Only description and remote_mcp are used; the others configured the local gateway
# server that earlier versions shipped and are accepted, and ignored, so existing files keep working.
LEGACY_KEYS = {
    "api_url", "sso_issuer", "sso_client_id", "sso_scopes", "sso_audience", "sso_token_type", "sso_redirect_port",
    "use_env_secrets", "use_plugin_secrets",
}
KNOWN_KEYS = {"description", "remote_mcp"} | LEGACY_KEYS


class EnvConfigError(Exception):
    """A problem with an environments file or the active environment, worded for the user."""


@dataclass(frozen=True)
class Environment:
    name: str
    source: Path
    description: str = ""
    url: str = ""
    client_id: str = ""
    callback_port: Optional[int] = None
    scopes: str = ""

    @property
    def has_remote(self) -> bool:
        return bool(self.url)

    def server_config(self) -> Dict[str, Any]:
        """The JSON for ``claude mcp add-json``."""
        oauth: Dict[str, Any] = {}
        if self.client_id:
            oauth["clientId"] = self.client_id
        if self.callback_port:
            oauth["callbackPort"] = self.callback_port
        if self.scopes:
            oauth["scopes"] = self.scopes
        config: Dict[str, Any] = {"type": "http", "url": self.url}
        if oauth:
            config["oauth"] = oauth
        return config


# ── Locations ─────────────────────────────────────────────────────────────────────────────────────────────────


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-mcp"


def state_file() -> Path:
    return config_dir() / "active-environment.json"


def resolve_file(path: str) -> Path:
    """An environments file named by the user, as an absolute path (the state outlives the current directory)."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise EnvConfigError(f"Environments file not found: {resolved}")
    return resolved


# ── Loading ───────────────────────────────────────────────────────────────────────────────────────────────────


def parse_file(path: Path) -> Dict[str, Environment]:
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
    secrets = sorted(set(raw) & SECRET_KEYS)
    if secrets:
        raise EnvConfigError(f"{where} contains {', '.join(secrets)}. Secrets don't belong in this file; remove them.")
    unknown = sorted(set(raw) - KNOWN_KEYS)
    if unknown:
        raise EnvConfigError(f"{where}: unknown key(s) {', '.join(unknown)}. Known keys: description, remote_mcp.")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise EnvConfigError(f"{where}: description must be a string.")
    remote = raw.get("remote_mcp")
    if remote is None:
        return Environment(name, path, description)
    return _parse_remote(name, path, description, remote, f"{where}: remote_mcp")


def _parse_remote(name: str, path: Path, description: str, raw: Any, where: str) -> Environment:
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
    return Environment(name, path, description, url, client_id.strip(), port, scopes.strip())


def read_state() -> Optional[Dict[str, Any]]:
    path = state_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("name"), str) else None


def _write_state(data: Optional[Dict[str, Any]]) -> None:
    path = state_file()
    if data is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".active-environment.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, str(path))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Switching ─────────────────────────────────────────────────────────────────────────────────────────────────

Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]


def _run(args: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, check=False, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def _remote_registered(run: Runner) -> bool:
    """Whether a user-scope ``unizo-cloud`` server exists."""
    result = run(["claude", "mcp", "get", REMOTE_SERVER_NAME])
    return result.returncode == 0 and "Scope: User" in result.stdout


def _detail(result: "subprocess.CompletedProcess[str]") -> str:
    return (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"


def use(name: str, *, file: Path, force: bool = False, run: Runner = _run, out: Callable[[str], None] = print) -> Environment:
    """Makes ``name`` (looked up in ``file``) the active environment and registers its remote MCP server."""
    envs = parse_file(file)
    if name not in envs:
        available = ", ".join(sorted(envs)) or "none"
        raise EnvConfigError(f'No environment named "{name}". Available: {available} in {file}.')
    env = envs[name]
    if not env.has_remote:
        raise EnvConfigError(f'Environment "{name}" in {file} has no remote_mcp.url, so there is nothing to connect to.')

    state = read_state()
    owned = bool(state and state.get("remote_registered"))
    exists = _remote_registered(run)
    if exists and not owned and not force:
        raise EnvConfigError(
            f'A user-scope MCP server named "{REMOTE_SERVER_NAME}" already exists and wasn\'t added by this '
            "command. Remove it (claude mcp remove --scope user unizo-cloud) or run again with --force to replace it."
        )

    new_remote = env.server_config()
    if exists:
        if (state or {}).get("remote") != new_remote:
            # Claude Code keeps a server's OAuth client registration and tokens by name, and a cached registration
            # wins over a changed clientId. Sign out so the next sign-in uses this environment's client.
            run(["claude", "mcp", "logout", REMOTE_SERVER_NAME])
        removed = run(["claude", "mcp", "remove", "--scope", "user", REMOTE_SERVER_NAME])
        if removed.returncode != 0:
            raise EnvConfigError(f"Couldn't remove the old {REMOTE_SERVER_NAME} server: {_detail(removed)}")
    added = run(["claude", "mcp", "add-json", "--scope", "user", REMOTE_SERVER_NAME, json.dumps(new_remote)])
    if added.returncode != 0:
        raise EnvConfigError(f"Couldn't register the remote MCP server: {_detail(added)}")

    _write_state(
        {
            "name": env.name,
            "source": str(env.source),
            "remote": new_remote,
            "remote_registered": True,
            "activated_at": _now(),
        }
    )
    out(f'Active Unizo environment: {env.name}{f" ({env.description})" if env.description else ""}')
    out(f"  remote MCP: {env.url}")
    out(f"  client ID:  {env.client_id or '(dynamic client registration)'}")
    out("Restart Claude Code to apply, then sign in: /mcp -> unizo-cloud -> Authenticate.")
    return env


def off(*, run: Runner = _run, out: Callable[[str], None] = print) -> None:
    """Deactivates environments and removes the ``unizo-cloud`` server this script added."""
    state = read_state()
    if state is None:
        out("No Unizo environment is active.")
        return
    if state.get("remote_registered") and _remote_registered(run):
        run(["claude", "mcp", "logout", REMOTE_SERVER_NAME])
        run(["claude", "mcp", "remove", "--scope", "user", REMOTE_SERVER_NAME])
    _write_state(None)
    out(f'Deactivated environment "{state["name"]}" and removed {REMOTE_SERVER_NAME}. Restart Claude Code to apply.')


def mark_setup_complete(*, out: Callable[[str], None] = print) -> None:
    """Records that /unizo:unizo-plugin-configure finished for the active environment, so the onboarding hook goes quiet.

    Switching environments rewrites the state without this flag, so the next environment is set up again."""
    state = read_state()
    if state is None:
        raise EnvConfigError("No Unizo environment is active. Run /unizo:unizo-plugin-configure to pick one first.")
    state["setup_complete"] = True
    state["setup_completed_at"] = _now()
    _write_state(state)
    out(f'Setup recorded as complete for environment "{state["name"]}".')


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────────────

USAGE = """usage: unizo_env.py [list --file <path> | current | use <name> --file <path> [--force] | off | setup-done]

  list           environments in the file (* marks the active one)
  --file <path>  the environments file to read (required for list and use; there is no default file)
  current        the active environment and the unizo-cloud registration it made
  use <name>     make <name> active and register its remote MCP server as unizo-cloud
  off            remove the unizo-cloud server this command added and forget the active environment
  setup-done     record that /unizo:unizo-plugin-configure finished for the active environment"""


def _pop_file(args: List[str]) -> Tuple[List[str], Optional[Path]]:
    """Removes ``--file <path>`` / ``-f <path>`` / ``--file=<path>`` from ``args``."""
    rest: List[str] = []
    file: Optional[Path] = None
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


def cli(args: List[str]) -> int:
    try:
        args, file = _pop_file(args)
        command = args[0] if args else "list"
        if command in ("list", "use") and file is None:
            raise EnvConfigError(f"{command} needs --file <path-to-environments.json>. There is no default environments file.")
        if command == "list":
            assert file is not None
            envs = parse_file(file)
            state = read_state() or {}
            active = state.get("name") if state.get("source") == str(file) else None
            if not envs:
                print(f"No environments found in {file}.")
                return 1
            for name in sorted(envs):
                env = envs[name]
                mark = "*" if name == active else " "
                desc = f"  {env.description}" if env.description else ""
                print(f"{mark} {name:<14}{env.url or '(no remote_mcp)':<40}{desc}")
            return 0
        if command == "current":
            state = read_state()
            if state is None:
                print("No Unizo environment is active.")
                return 0
            print(f"{state['name']}  (from {state.get('source', '?')}, since {state.get('activated_at', '?')})")
            print(f"  remote_mcp: {json.dumps(state.get('remote'))}")
            print(f"  setup complete: {bool(state.get('setup_complete'))}")
            return 0
        if command == "use" and len(args) >= 2:
            assert file is not None
            use(args[1], file=file, force="--force" in args[2:])
            return 0
        if command == "off":
            off()
            return 0
        if command == "setup-done":
            mark_setup_complete()
            return 0
        print(USAGE, file=sys.stderr)
        return 2
    except EnvConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e.filename or 'claude'} not found. The Claude Code CLI must be on PATH.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
