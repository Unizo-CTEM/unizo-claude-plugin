"""Tests for hooks/unizo_onboard.py, run as Claude Code runs it at session start."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "unizo_onboard.py"


def run(extra_env: dict[str, str] | None = None) -> dict[str, Any] | None:
    env = os.environ.copy()
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}),
        capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def write_state(isolated_config: Path, state: dict[str, Any]) -> None:
    path = isolated_config / "config" / "unizo-mcp" / "active-environment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def test_fresh_install_points_claude_to_setup_without_a_banner() -> None:
    out = run()
    assert out is not None
    assert "systemMessage" not in out
    assert "/unizo:unizo-plugin-configure" in out["hookSpecificOutput"]["additionalContext"]
    assert "environments.json" in out["hookSpecificOutput"]["additionalContext"]


def test_environment_picked_but_setup_unfinished_finishes_it(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging"})
    out = run()
    assert out is not None
    assert '"staging"' in out["systemMessage"] and "first message" in out["systemMessage"]
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "unizo:unizo-plugin-configure" in context
    assert "without asking" in context
    assert "OAuth" in context and "unizo_login" not in context


def test_registration_from_an_older_version_asks_to_switch_again(isolated_config: Path) -> None:
    write_state(isolated_config, {
        "name": "dev52",
        "source": "/home/me/envs.json",
        "remote": {"type": "http", "url": "https://dev52/mcp", "headersHelper": "old-unizo-helper headers"},
        "setup_complete": True,
    })
    out = run()
    assert out is not None
    assert '"dev52"' in out["systemMessage"] and "older plugin version" in out["systemMessage"]
    assert "/unizo:unizo-plugin-configure /home/me/envs.json dev52" in out["hookSpecificOutput"]["additionalContext"]


def test_setup_complete_is_silent(isolated_config: Path) -> None:
    write_state(isolated_config, {"name": "staging", "setup_complete": True})
    assert run() is None


def test_corrupt_state_never_breaks_the_session(isolated_config: Path) -> None:
    path = isolated_config / "config" / "unizo-mcp" / "active-environment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    out = run()
    assert out is not None and "/unizo:unizo-plugin-configure" in out["hookSpecificOutput"]["additionalContext"]
