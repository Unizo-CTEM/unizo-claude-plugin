"""Tests for hooks/unizo_guard.py, run as Claude Code runs it: a subprocess fed the hook event on stdin."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

GUARD = Path(__file__).resolve().parents[2] / "hooks" / "unizo_guard.py"
SESSION = "sess-1"


def run(mode: str, tool: str, tool_input: dict[str, Any], response: Any = None) -> dict[str, Any] | None:
    event = {
        "session_id": SESSION,
        "hook_event_name": "PreToolUse" if mode == "pre" else "PostToolUse",
        "tool_name": f"mcp__unizo-cloud__{tool}",
        "tool_input": tool_input,
    }
    if mode == "post":
        event["tool_response"] = response if response is not None else {"ok": True}
    proc = subprocess.run(
        [sys.executable, str(GUARD), mode],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def verdict(out: dict[str, Any] | None) -> str | None:
    return out["hookSpecificOutput"]["permissionDecision"] if out else None


COMMIT = {"investigation_id": "INV-1", "plan_key": "PLAN-01", "action_keys": ["PA-01"], "confirmed": True}


def test_reads_pass_silently() -> None:
    assert run("pre", "find_investigations", {"state": "AWAITING_REVIEW"}) is None
    assert run("pre", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01"}) is None


@pytest.mark.parametrize("tool", ["move_ticket", "set_jira_assignee"])
def test_ticket_moves_are_denied(tool: str) -> None:
    assert verdict(run("pre", tool, {"investigation_id": "INV-1"})) == "deny"


@pytest.mark.parametrize("tool", ["assign_investigation", "select_plan", "reject_plan", "abandon_investigation"])
def test_other_writes_ask(tool: str) -> None:
    assert verdict(run("pre", tool, {"investigation_id": "INV-1"})) == "ask"


def test_commit_without_preview_is_denied() -> None:
    out = run("pre", "commit_actions", COMMIT)
    assert verdict(out) == "deny"
    assert "preview_commit" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_commit_after_whole_plan_preview_asks() -> None:
    run("post", "preview_commit", {"investigation_id": "inv-1", "plan_key": "plan-01"})
    assert verdict(run("pre", "commit_actions", COMMIT)) == "ask"


def test_commit_of_unpreviewed_action_is_denied() -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01", "action_keys": ["PA-02"]})
    out = run("pre", "commit_actions", COMMIT)
    assert verdict(out) == "deny"
    assert "PA-01" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_commit_of_other_plan_is_denied() -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-02"})
    assert verdict(run("pre", "commit_actions", COMMIT)) == "deny"


def test_failed_preview_does_not_count() -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01"}, {"isError": True})
    assert verdict(run("pre", "commit_actions", COMMIT)) == "deny"


def test_commit_without_confirmed_is_denied() -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01"})
    assert verdict(run("pre", "commit_actions", {**COMMIT, "confirmed": False})) == "deny"


def test_stale_preview_is_denied(isolated_config: Path) -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01"})
    state_file = isolated_config / "config" / "unizo-mcp" / "hook-state" / f"{SESSION}.json"
    state = json.loads(state_file.read_text())
    state["previews"]["INV-1|PLAN-01"]["at"] = time.time() - 31 * 60
    state_file.write_text(json.dumps(state))
    assert verdict(run("pre", "commit_actions", COMMIT)) == "deny"


def test_reject_plan_invalidates_previews() -> None:
    run("post", "preview_commit", {"investigation_id": "INV-1", "plan_key": "PLAN-01"})
    run("post", "reject_plan", {"investigation_id": "INV-1", "plan_key": "PLAN-02", "reason": "no"})
    assert verdict(run("pre", "commit_actions", COMMIT)) == "deny"


def test_writes_are_audited_and_reads_are_not(isolated_config: Path) -> None:
    run("post", "find_investigations", {"state": "AWAITING_REVIEW"})
    run("post", "assign_investigation", {"investigation_id": "INV-1"}, {"jiraAssigneeSet": True})
    audit = isolated_config / "config" / "unizo-mcp" / "audit.jsonl"
    lines = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [line["tool"] for line in lines] == ["assign_investigation"]
    assert lines[0]["failed"] is False
    assert oct(audit.stat().st_mode & 0o777) == "0o600"


def test_garbage_input_is_ignored() -> None:
    proc = subprocess.run([sys.executable, str(GUARD), "pre"], input="not json", capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout == ""
