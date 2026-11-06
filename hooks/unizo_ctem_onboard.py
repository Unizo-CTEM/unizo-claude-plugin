#!/usr/bin/env python3
"""SessionStart hook: walk new users through /unizo-ctem:unizo-ctem-setup.

Claude Code has no plugin install hook, so this runs at the start of every session; the first session after
installing the plugin is where onboarding starts. It has three outcomes:

* nothing set up (no active environment, no ``UNIZO_CTEM_API_URL`` in the environment): no message is shown, but
  Claude is told to offer ``/unizo-ctem:unizo-ctem-setup``, which asks for their environments.json, switches to an environment, and signs in.
* an environment is active but setup hasn't finished (the switch needs a restart, so setup always spans two sessions):
  ask the user to run ``/unizo-ctem:unizo-ctem-setup`` again to sign in to the gateway and to ``unizo-ctem-cloud``.
* setup finished (``unizo-ctem-mcp env setup-done``), or ``UNIZO_CTEM_API_URL`` sets a gateway with no environment:
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
    return Path(base) / "unizo-ctem-mcp"


def active_state() -> dict[str, Any] | None:
    try:
        state = json.loads((config_dir() / "active-environment.json").read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("name") else None


def has_configured_gateway() -> bool:
    return bool(os.environ.get("UNIZO_CTEM_API_URL", "").strip())


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
            "The Unizo CTEM plugin was just installed and isn't set up: no CTEM environment is active and no gateway "
            "URL is configured. In your first reply, whatever the user asks, offer to run /unizo-ctem:unizo-ctem-setup. "
            "It asks for the path to their environments.json, switches to an environment, and then signs them in. "
            "Don't attempt CTEM work before that.",
        )
        return
    if state.get("setup_complete"):
        return
    name = state["name"]
    emit(
        f'Unizo CTEM: environment "{name}" is active. Run /unizo-ctem:unizo-ctem-setup to finish signing in.',
        f'The Unizo CTEM environment "{name}" was selected in an earlier session, but setup isn\'t finished: the user '
        "still has to sign in to the CTEM gateway (SSO) and to the remote unizo-ctem-cloud MCP server. In your first "
        "reply, offer to run /unizo-ctem:unizo-ctem-setup to finish both sign-ins.",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never break the session
        pass
