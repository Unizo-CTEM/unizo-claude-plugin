"""Tests for hooks/unizo_ctem_onboard.py, run as Claude Code runs it at session start."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "unizo_ctem_onboard.py"


def run(extra_env: dict[str, str] | None = None) -> dict[str, Any] | None:
    env = os.environ.copy()
    env.pop("CLAUDE_PLUGIN_OPTION_API_URL", None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}),
        capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def write_state(isolated_config: Path, state: dict[str, Any]) -> None:
    path = isolated_config / "config" / "unizo-ctem-mcp" / "active-environment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def test_fresh_install_points_to_setup() -> None:
    out = run()
    assert out is not None
    assert "/unizo-ctem:unizo-ctem-setup" in out["systemMessage"]
    assert "environments.json" in out["hookSpecificOutput"]["additionalContext"]


def test_plugin_options_gateway_without_environment_is_silent() -> None:
    assert run({"CLAUDE_PLUGIN_OPTION_API_URL": "https://ctem.acme.com"}) is None


def test_environment_picked_but_not_signed_in_asks_to_finish(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging"})
    out = run()
    assert out is not None
    assert '"staging"' in out["systemMessage"] and "finish" in out["systemMessage"]
    assert "unizo-ctem-cloud" in out["hookSpecificOutput"]["additionalContext"]


def test_setup_complete_is_silent(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging", "setup_complete": True})
    assert run() is None


def test_corrupt_state_never_breaks_the_session(isolated_config: Path) -> None:
    path = isolated_config / "config" / "unizo-ctem-mcp" / "active-environment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    out = run()
    assert out is not None and "/unizo-ctem:unizo-ctem-setup" in out["systemMessage"]
