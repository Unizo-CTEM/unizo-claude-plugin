#!/usr/bin/env python3
"""SessionStart hook: walk new users through /unizo:unizo-plugin-configure.

Claude Code has no plugin install hook, so this runs at the start of every session; the first session after
installing the plugin is where onboarding starts. Outcomes:

* nothing set up (no active environment): no message is shown, but Claude is told to offer
  ``/unizo:unizo-plugin-configure``, which asks for the environments.json and registers ``unizo-cloud``.
* the active environment was registered by an earlier plugin version, whose ``unizo-cloud`` got its token from a
  local helper that no longer exists: tell the user, and have Claude switch to the same environment again.
* an environment is active but setup hasn't finished (registering ``unizo-cloud`` needs a restart, so setup always
  spans two sessions): tell the user setup finishes with their first message, and tell Claude to run
  ``/unizo:unizo-plugin-configure`` in its first reply without asking. It signs ``unizo-cloud`` in with Claude Code's
  OAuth and checks the connection. A hook can't start a turn on its own, so the user's first message kicks it off.
* setup finished (``unizo_env.py setup-done``): stay silent.

Standard library only. It never raises: a hook crash must not break the session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-mcp"


def active_state() -> Optional[Dict[str, Any]]:
    try:
        state = json.loads((config_dir() / "active-environment.json").read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("name") else None


def emit(message: Optional[str], context: str) -> None:
    """Prints the hook output. ``message`` is shown to the user; ``None`` keeps the hook silent on screen."""
    out: Dict[str, Any] = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    if message:
        out["systemMessage"] = message
    print(json.dumps(out))


def main() -> None:
    state = active_state()
    if state is None:
        emit(
            None,
            "The Unizo plugin isn't set up: no Unizo environment is active. In your first reply, whatever the user "
            "asks, offer to run /unizo:unizo-plugin-configure. It asks for the path to their environments.json, "
            "registers the unizo-cloud MCP server for the environment they pick, and signs them in. Don't attempt "
            "Unizo work before that.",
        )
        return
    name = str(state["name"])
    remote = state.get("remote")
    if isinstance(remote, dict) and remote.get("headersHelper"):
        source = state.get("source") or "<environments.json>"
        emit(
            f'Unizo: environment "{name}" was set up by an older plugin version and must be switched again.',
            f'The Unizo environment "{name}" was registered by an older version of this plugin: its unizo-cloud server '
            "gets its sign-in from a local helper that this version no longer ships, so unizo-cloud will fail to "
            "connect. In your first reply, whatever the user says, tell them so in one line and offer to run "
            f"/unizo:unizo-plugin-configure {source} {name} to register it again. Once they agree, follow that "
            "command; it needs one more restart and a sign-in through /mcp.",
        )
        return
    if state.get("setup_complete"):
        return
    emit(
        f'Unizo: environment "{name}" is active. Setup finishes with your first message.',
        f'The Unizo environment "{name}" was selected in an earlier session and Claude Code has since restarted, '
        "but setup isn't finished. In your first reply, whatever the user says, finish it right away without asking "
        "first: invoke the unizo:unizo-plugin-configure skill with the Skill tool (no arguments) and follow it. It "
        "skips the environment step, signs unizo-cloud in with Claude Code's OAuth if needed, and checks the "
        "connection. Once setup is done, get back to what the user asked.",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never break the session
        pass
