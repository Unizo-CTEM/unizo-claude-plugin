#!/usr/bin/env python3
"""Guard hook for the remote ``unizo-cloud`` MCP server's tools.

Claude Code runs this for every ``mcp__unizo-cloud__*`` call (see hooks.json):

    unizo_guard.py pre    PreToolUse:  block, ask or let the call through
    unizo_guard.py post   PostToolUse: remember previews, audit writes

Rules (from the Unizo MCP Server Tool Catalog):

* A ticket only ever gets a comment over MCP, so ``move_ticket`` and ``set_jira_assignee`` are denied.
* ``commit_actions`` is denied unless ``preview_commit`` ran in this session, recently, for the same
  Investigation and plan, covering every action being committed. When it did, the user is still asked.
* Every other write asks the user first. Reads pass silently.
* Every write that ran is appended to ``<config>/unizo-mcp/audit.jsonl``.

Standard library only, so it runs with any python3. It never raises: a hook crash must not break the session,
but for ``commit_actions`` an internal error falls back to asking, never to allowing.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PREFIX = "mcp__unizo-cloud__"
PREVIEW_TTL_SECONDS = 30 * 60

DENIED = {
    "move_ticket": (
        "Over MCP a ticket only gets a comment (Tool Catalog rule 5). Use report_wrong_destination to record "
        "that it went to the wrong team and add_ticket_comment to tell them; a person moves it in the ITSM."
    ),
    "set_jira_assignee": (
        "Over MCP a ticket only gets a comment (Tool Catalog rule 5); reassigning in Jira is done by a person. "
        "To change the Unizo owner, use assign_investigation."
    ),
}

WRITES = {
    "abandon_investigation", "accept_compensating_control", "accept_exposure_risk", "add_exposure_comment",
    "add_identity_comment", "add_investigation_comment", "add_run_comment", "add_ticket_comment",
    "assign_investigation", "commit_actions", "contact_support", "create_manual_plan", "decide_declined_member",
    "edit_ticket_draft", "generate_report", "launch_playbook", "link_existing_ticket", "move_ticket",
    "redraft_plan", "reengage_investigation", "reject_plan", "report_wrong_destination", "select_plan", "set_jira_assignee",
    "start_investigation", "verify_exposure_now", "verify_run_now", "withdraw_risk_acceptance",
}

# What the user is told when asked to approve a write, in a few words.
ASK_REASON = {
    "assign_investigation": "Changes who owns this Investigation in Unizo (and may set the Jira assignee).",
    "select_plan": "Selects the plan to work from. Nothing is committed and no ticket is created.",
    "redraft_plan": "Asks Unizo to draft a different plan for this Investigation (at most three re-drafts).",
    "reject_plan": "Rejects a plan so it can no longer be committed. The reason is recorded.",
    "abandon_investigation": "Abandons the Investigation. Abandonment is not resolution.",
    "start_investigation": "Opens an Investigation and starts Unizo drafting plans.",
    "launch_playbook": "Launches a Playbook Run, which can open many Investigations.",
    "add_ticket_comment": "Adds a comment to a ticket in the customer's ITSM.",
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "unizo-mcp"


def state_path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return config_dir() / "hook-state" / f"{safe}.json"


def load_state(session_id: str) -> dict[str, Any]:
    try:
        return json.loads(state_path(session_id).read_text())
    except (OSError, ValueError):
        return {}


def save_state(session_id: str, state: dict[str, Any]) -> None:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def preview_key(tool_input: dict[str, Any]) -> str:
    return f"{str(tool_input.get('investigation_id', '')).strip().upper()}|{str(tool_input.get('plan_key', '')).strip().upper()}"


def decision(kind: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": kind,
            "permissionDecisionReason": reason,
        }
    }


def check_commit(event: dict[str, Any]) -> dict[str, Any]:
    tool_input = event.get("tool_input") or {}
    key = preview_key(tool_input)
    preview = load_state(event.get("session_id", "")).get("previews", {}).get(key)
    inv, plan = tool_input.get("investigation_id"), tool_input.get("plan_key")
    if not preview:
        return decision(
            "deny",
            f"Run preview_commit for {inv} {plan} first, with the same Investigation ID and plan key, and show "
            "the user where each ticket goes and which actions have a Hard gate. Then ask before committing.",
        )
    if time.time() - preview.get("at", 0) > PREVIEW_TTL_SECONDS:
        return decision(
            "deny",
            f"The preview of {inv} {plan} is over {PREVIEW_TTL_SECONDS // 60} minutes old and routing may have "
            "changed. Run preview_commit again.",
        )
    previewed = preview.get("action_keys")  # None means the whole plan was previewed
    wanted = [str(k).upper() for k in tool_input.get("action_keys") or []]
    if previewed is not None:
        missing = sorted(set(wanted) - set(previewed))
        if missing:
            return decision(
                "deny",
                f"Actions {', '.join(missing)} were not in the preview. Run preview_commit covering them.",
            )
    if not tool_input.get("confirmed"):
        return decision("deny", "commit_actions needs confirmed=true, set only after the user agreed.")
    return decision(
        "ask",
        f"Commit {', '.join(wanted)} of {inv} {plan}? This creates real tickets in the ITSM and cannot be undone.",
    )


def pre(event: dict[str, Any]) -> dict[str, Any] | None:
    tool = event.get("tool_name", "").removeprefix(PREFIX)
    if tool in DENIED:
        return decision("deny", DENIED[tool])
    if tool == "commit_actions":
        try:
            return check_commit(event)
        except Exception as exc:  # never allow a commit because the guard broke
            return decision("ask", f"The Unizo commit guard failed ({exc}); confirm this commit yourself.")
    if tool in WRITES:
        return decision("ask", ASK_REASON.get(tool, f"{tool} changes data in Unizo, recorded as you."))
    return None


def response_failed(response: Any) -> bool:
    if isinstance(response, dict):
        if response.get("isError") or response.get("is_error"):
            return True
        if "error" in response:
            return True
    text = json.dumps(response) if not isinstance(response, str) else response
    return '"isError": true' in text or text.lstrip().lower().startswith("error")


def post(event: dict[str, Any]) -> None:
    tool = event.get("tool_name", "").removeprefix(PREFIX)
    tool_input = event.get("tool_input") or {}
    response = event.get("tool_response")
    session_id = event.get("session_id", "")

    if tool == "preview_commit" and not response_failed(response):
        state = load_state(session_id)
        keys = tool_input.get("action_keys")
        state.setdefault("previews", {})[preview_key(tool_input)] = {
            "at": time.time(),
            "action_keys": [str(k).upper() for k in keys] if keys else None,
        }
        save_state(session_id, state)
    elif tool in {"reject_plan", "redraft_plan", "reengage_investigation", "edit_ticket_draft"} and not response_failed(response):
        # The plans or their ticket drafts changed: earlier previews of this Investigation no longer hold.
        state = load_state(session_id)
        inv = str(tool_input.get("investigation_id", "")).strip().upper()
        previews = state.get("previews", {})
        stale = [k for k in previews if k.split("|")[0] == inv]
        for k in stale:
            previews.pop(k, None)
        if stale:
            save_state(session_id, state)

    if tool in WRITES:
        line = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            "tool": tool,
            "input": tool_input,
            "failed": response_failed(response),
            "response": response,
        }
        path = config_dir() / "audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        if mode == "pre":
            out = pre(event)
            if out:
                print(json.dumps(out))
        elif mode == "post":
            post(event)
    except Exception as exc:  # a broken hook must not break the session
        print(f"unizo_guard: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
