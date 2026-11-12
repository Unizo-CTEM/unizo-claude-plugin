#!/usr/bin/env python3
"""SessionStart hook: walk new users through /unizo:unizo-plugin-configure.

Claude Code has no plugin install hook, so this runs at the start of every session; the first session after
installing the plugin is where onboarding starts. It has three outcomes:

* nothing set up (no active environment, no ``UNIZO_API_URL`` in the environment): no message is shown, but
  Claude is told to offer ``/unizo:unizo-plugin-configure``, which asks for their environments.json, switches to an environment, and signs in.
* an environment is active but setup hasn't finished (the switch needs a restart, so setup always spans two sessions):
  tell the user setup finishes with their first message, and tell Claude to run ``/unizo:unizo-plugin-configure``
  in its first reply without asking. The single SSO sign-in normally happened before the restart and also covers
  ``unizo-cloud``, so this checks the connection and signs in only if needed. A hook can't start a turn on
  its own, so the user's first message is what kicks it off.
* setup finished (``unizo-mcp env setup-done``), or ``UNIZO_API_URL`` sets a gateway with no environment:
  stay silent.

Standard library only. It never raises: a hook crash must not break the session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-mcp"


def active_state() -> dict[str, Any] | None:
    try:
        state = json.loads((config_dir() / "active-environment.json").read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("name") else None


def has_configured_gateway() -> bool:
    return bool(os.environ.get("UNIZO_API_URL", "").strip())


def emit(message: str | None, context: str) -> None:
    """Prints the hook output. ``message`` is shown to the user; ``None`` keeps the hook silent on screen."""
    out: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    if message:
        out["systemMessage"] = message
    print(json.dumps(out))


def main() -> None:
    state = active_state()
    if state is None:
        if has_configured_gateway():
            return
        emit(
            None,
            "The Unizo plugin was just installed and isn't set up: no Unizo environment is active and no gateway "
            "URL is configured. In your first reply, whatever the user asks, offer to run /unizo:unizo-plugin-configure. "
            "It asks for the path to their environments.json, switches to an environment, and then signs them in. "
            "Don't attempt Unizo work before that.",
        )
        return
    if state.get("setup_complete"):
        return
    name = state["name"]
    emit(
        f'Unizo: environment "{name}" is active. Setup finishes with your first message.',
        f'The Unizo environment "{name}" was selected in an earlier session and Claude Code has since restarted, '
        "but setup isn't finished. In your first reply, whatever the user says, finish it right away without asking "
        "first: invoke the unizo:unizo-plugin-configure skill with the Skill tool (no arguments) and follow it from "
        "step 0. It skips the environment step and checks the connection. One SSO sign-in covers both the Unizo "
        "gateway and the remote unizo-cloud server; sign in (unizo_login) only if the gateway isn't signed "
        "in, and use mcp__unizo-cloud__authenticate only as the last resort the command describes. Once setup "
        "is done, get back to what the user asked.",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never break the session
        pass
