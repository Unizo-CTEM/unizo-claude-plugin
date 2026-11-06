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
    env.pop("UNIZO_CTEM_API_URL", None)
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


def test_fresh_install_points_claude_to_setup_without_a_banner() -> None:
    out = run()
    assert out is not None
    assert "systemMessage" not in out
    assert "/unizo-ctem:unizo-ctem-plugin-configure" in out["hookSpecificOutput"]["additionalContext"]
    assert "environments.json" in out["hookSpecificOutput"]["additionalContext"]


def test_env_var_gateway_without_environment_is_silent() -> None:
    assert run({"UNIZO_CTEM_API_URL": "https://ctem.acme.com"}) is None


def test_environment_picked_but_setup_unfinished_finishes_it(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging"})
    out = run()
    assert out is not None
    assert '"staging"' in out["systemMessage"] and "first message" in out["systemMessage"]
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "unizo-ctem:unizo-ctem-plugin-configure" in context
    assert "without asking" in context
    assert "One SSO sign-in covers both" in context


def test_setup_complete_is_silent(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging", "setup_complete": True})
    assert run() is None


def test_corrupt_state_never_breaks_the_session(isolated_config: Path) -> None:
    path = isolated_config / "config" / "unizo-ctem-mcp" / "active-environment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    out = run()
    assert out is not None and "/unizo-ctem:unizo-ctem-plugin-configure" in out["hookSpecificOutput"]["additionalContext"]
