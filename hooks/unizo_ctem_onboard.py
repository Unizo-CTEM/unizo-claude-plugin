#!/usr/bin/env python3
"""SessionStart hook: nudge first-time users to pick a CTEM environment.

Claude Code has no plugin install hook, so this runs at the start of every session and stays silent once the plugin
is usable: an environment is active (``unizo-ctem-mcp env use <name>``) or a gateway URL is set with
``/plugin configure``. Otherwise it shows the user a one-line hint and asks Claude to offer
``/unizo-ctem:unizo-ctem-env``.

Standard library only. It never raises: a hook crash must not break the session.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-ctem-mcp"


def has_active_environment() -> bool:
    try:
        state = json.loads((config_dir() / "active-environment.json").read_text())
        return bool(isinstance(state, dict) and state.get("name"))
    except (OSError, ValueError):
        return False


def has_configured_gateway() -> bool:
    return bool(os.environ.get("CLAUDE_PLUGIN_OPTION_API_URL", "").strip())


def main() -> None:
    if has_active_environment() or has_configured_gateway():
        return
    print(
        json.dumps(
            {
                "systemMessage": "Unizo CTEM: no environment selected yet. Run /unizo-ctem:unizo-ctem-env <path-to-environments.json> to pick one.",
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        "The Unizo CTEM plugin is installed but not set up: no CTEM environment is active and no "
                        "gateway URL is configured. Before any CTEM work, and the first time the user mentions CTEM, "
                        "ask for the path to their environments file and run /unizo-ctem:unizo-ctem-env <path> so they can pick an "
                        "environment from it (or /unizo-ctem:unizo-ctem-env with no argument for the bundled ones)."
                    ),
                },
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never break the session
        pass
