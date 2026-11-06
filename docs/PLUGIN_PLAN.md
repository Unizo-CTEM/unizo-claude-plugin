# CTEM plugin plan: skills, agents, hooks and permissions

**Date:** 6 November 2026
**Based on:** *Unizo MCP Server — Tool Catalog* (working draft, revised 29 October 2026, Single Pane Draft 12) and the live `unizo-ctem-cloud` server on dev52.
**Status:** In progress. W1 is built (6 November 2026): skill `unizo-ctem-review-queue`, command `/unizo-ctem:unizo-ctem-queue`, and the `unizo_ctem_guard` hook, which covers hooks 1–4 of section 4.4 for every `unizo-ctem-cloud` tool. Everything else is still a proposal.

**Found while building W1 (add to section 3):** `find_exposures(kev_listed=true, crown_jewel=true)` returns 0 results on dev52, even though KEV-listed rows carry `crownJewel: true`. The skill works around it by filtering on the row field.

---

## 1. Where things stand

| Part | State |
|---|---|
| Local `unizo-ctem` MCP server (`mcp-server/`) | Connection, SSO and environments only: `unizo_ctem_status`, `unizo_ctem_login`, `unizo_ctem_logout`. Signed in to dev52 as dev1_user. |
| Remote `unizo-ctem-cloud` MCP server | 99 tools. All CTEM work goes through it. A test call works (W1 queue: 7,906 Investigations awaiting review). |
| Commands | `/unizo-ctem:unizo-ctem-setup`, `/unizo-ctem:unizo-ctem-env`, `/unizo-ctem:unizo-ctem-hello` |
| Skills | `unizo-ctem-basics` (general CTEM concepts) |
| Agents | `exposure-triage` (generic reasoning; calls no tools) |
| Hooks | None |

**Rule:** `unizo-ctem-cloud` is the source of truth for CTEM data and actions. The local `unizo-ctem` server stays as the auth and environment helper and does not duplicate `unizo-ctem-cloud` tools.

---

## 2. Using the plugin today

Start every session by calling `get_my_context`. It gives the vocabulary, the available and refused tools, and the feature flags (`findingsIntake`, `graphQuery`).

| Workflow | What to ask | Live tool sequence |
|---|---|---|
| W1 Review queue | "What's waiting for my review, crown jewels first?" | `find_investigations(state=AWAITING_REVIEW)` → `assign_investigation` → `get_investigation` → `preview_commit` → `commit_actions` |
| W2 Exposure to verified closure | "Critical Exposures reaching crown jewels; investigate the first" | `find_exposures` → `get_exposure` → `start_investigation` → `await_investigation_draft` → `preview_commit` → `commit_actions` → `get_ticket` / `get_ticket_history` → `get_exposure_verification` |
| W3 Scan intake | "Which of these scan findings are real Exposures?" | **Can't run yet:** `findingsIntake` is false and the intake tools are missing |
| W4 CVE outbreak | "CVE-X is being exploited, what do we have?" | `find_threats` / `get_vulnerability` → `preview_cve_scope` → `list_playbooks` → `launch_playbook` → `get_run` → `get_run_output` |
| W5 Asset or identity | "Tell me about payments-api" | `search_all` → `get_asset` / `get_identity` → `list_asset_findings` |
| W6 Keep work moving | "What did we send out that hasn't moved?" | `find_open_tickets` → `get_ticket_history` → `report_wrong_destination` → `add_ticket_comment` |
| W7 Weekly vulnerability review | "Exploited vulns in Production over 30 days, by business unit" | `find_vulnerabilities`, `find_findings`, `get_vulnerability`. Partial: no `find_tickets` and no `get_patch_window` |
| W8 Department head brief | "One page on Finance for their VP" | `get_posture_summary`, `export_dashboard`, `find_findings`, `find_exposures`. Partial: no `get_organization_posture` |

---

## 3. Where the live server differs from the catalog

Raise these with engineering. The plugin can only work around them.

### 3.1 Rule breaks

| Issue | Catalog rule | Live behaviour |
|---|---|---|
| Ticket moves and reassignment | Rule 5 and section 5: over MCP a ticket only ever gets a comment | `move_ticket`, `list_ticket_destinations` and `set_jira_assignee` are live and change the ITSM |
| Scopes not enforced | Rule 2: what an app may do is a token property; a read-only connection can never commit | `get_my_context` returns `scopes: []`, "Token scopes are not carried through yet", and nothing is refused |

### 3.2 Now tools missing from the server

| Catalog tool | Workflow | Live substitute |
|---|---|---|
| `evaluate_findings`, `submit_findings`, `get_findings_outcome`, `withdraw_findings` | W3 | None (`findingsIntake: false`) |
| `find_tickets` | W7 | `find_open_tickets` (open tickets only) |
| `get_vulnerability_timeline` | W4 | None |
| `get_asset_history` | W5 | None |
| `list_teams` | W5, W7, W8 | None |
| `get_patch_window` | W7, W8 | `get_sla_policy` covers Investigation SLAs, which the catalog says are a different thing |
| `get_organization_posture` | W8 | `export_dashboard` partly covers it |
| `redraft_plan` | W1, W2 | `reengage_investigation`, `reject_plan`, `select_plan` (different model) |

### 3.3 Filter and paging gaps

- `find_investigations` has no KEV, reaches-crown-jewel or owner=me filters, so the W1 prompt can't be answered exactly. "Me" needs an `assignee_id`, looked up with `get_my_context` or `find_users`.
- Page sizes don't match the catalog (50 default, 200 maximum): `find_investigations` allows at most 100 and `find_threats` at most 50.

### 3.4 Live but not in the catalog's Now set

- Later tools already live: `accept_exposure_risk`, `withdraw_risk_acceptance`, `verify_exposure_now`, `link_existing_ticket`, `find_reports`, `get_report`, `generate_report`.
- Tools the catalog doesn't name: `add_exposure_comment`, `add_identity_comment`, `add_investigation_comment`, `add_run_comment`, `decide_declined_member`, `edit_ticket_draft`, `accept_compensating_control`, `verify_run_now`, `find_threats`, `get_advisory`, `preview_cve_scope`, plus several config reads (`list_routing_rules`, `list_suppression_policies`, `get_approval_policy` and others).
- Either the catalog or the server should be brought into line.

---

## 4. Plugin additions

### 4.1 Skills, one per workflow

The catalog (section 4, "Resources and prompts") asks for workflow prompts. Skills deliver the same thing in Claude Code.

| Skill | Workflow | Notes |
|---|---|---|
|` | W1 | Works around the missing filters: filters on crown jewel client-side and says it did |
| `unizo-ctem-work-exposure` | W2 | Uses `await_investigation_draft` instead of polling |
| `unizo-ctem-cve-response` | W4 | `find_threats` first, then `preview_cve_scope` before `launch_playbook` |
| `unizo-ctem-ticket-followup` | W6 | Comment-only; never suggests `move_ticket` or `set_jira_assignee` |
| `unizo-ctem-weekly-vuln-review` | W7 | Names the parts it can't answer yet (patch window, tickets Unizo can't confirm) |
| `unizo-ctem-bu-brief` | W8 | One page; never a score, rank or grade |
| `unizo-ctem-scan-intake` | W3 | Gated: checks `features.findingsIntake` first and stops with a clear message if it's false |

Every skill must:
1. Call `get_my_context` first.
2. Use Unizo terms: "drafted by Unizo", never "AI"; none of the forbidden terms ("identity risk score", "asset risk score", "riskiest identities", "case", "job", "campaign").
3. Say what every count counts, and when stale data was last seen.
4. Run `preview_commit` before `commit_actions`.
5. Confirm with the user before any write.

Also update `unizo-ctem-basics` to map the five CTEM stages to Unizo's objects (Exposure, Investigation, Plan, action, Run).

### 4.2 Commands

| Command | Starts |
|---|---|
| `/unizo-ctem:unizo-ctem-queue` | `unizo-ctem-review-queue` |
| `/unizo-ctem:cve <id>` | `unizo-ctem-cve-response` |
| `/unizo-ctem:weekly-review` | `unizo-ctem-weekly-vuln-review` |
| `/unizo-ctem:brief <business unit>` | `unizo-ctem-bu-brief` |

### 4.3 Agents

| Agent | Change |
|---|---|
| `exposure-triage` | Rewrite so it looks things up with `search_all`, `get_vulnerability` and `get_exposure`, and grounds its priority in Unizo's data instead of generic reasoning |
| `unizo-ctem-analyst` (new) | Read-only: its tool list is limited to `mcp__unizo-ctem-cloud__find_*`, `get_*`, `list_*` and `preview_*`. This gives a read-only mode on the client side until scopes are enforced on the server |

### 4.4 Hooks (`hooks/hooks.json`)

| # | Event | Matcher | Behaviour |
|---|---|---|---|
| 1 | PreToolUse | `mcp__unizo-ctem-cloud__(move_ticket\|set_jira_assignee\|list_ticket_destinations)` | `deny`, with the reason "Over MCP a ticket only gets a comment; use report_wrong_destination and add_ticket_comment" |
| 2 | PreToolUse | All write tools: `commit_actions`, `launch_playbook`, `start_investigation`, `assign_investigation`, `abandon_investigation`, `create_manual_plan`, `reengage_investigation`, `reject_plan`, `select_plan`, `accept_.*`, `withdraw_risk_acceptance`, `add_.*_comment`, `edit_ticket_draft`, `link_existing_ticket`, `report_wrong_destination`, `verify_.*_now`, `generate_report`, `decide_declined_member` | `ask`, so a person confirms every write |
| 3 | PreToolUse + PostToolUse | `commit_actions` / `preview_commit` | PostToolUse records each `preview_commit` (investigation and plan) in a session file. PreToolUse refuses `commit_actions` unless a preview for the same plan is on record |
| 4 | PostToolUse | Write tools (as in hook 2) | Append tool, inputs, outcome and time to `~/.config/unizo-ctem-mcp/audit.jsonl` |
| 5 | SessionStart | — | Run `unizo-ctem-mcp env current` and remind Claude to call `get_my_context` first |
| 6 | Stop (optional) | — | Scan Claude's last answer for forbidden terms and ask for a rewrite if one appears |

Example for hook 1:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__unizo-ctem-cloud__(move_ticket|set_jira_assignee|list_ticket_destinations)",
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Over MCP a ticket only gets a comment. Use report_wrong_destination and add_ticket_comment; a person moves the ticket in the ITSM.\"}}'"
          }
        ]
      }
    ]
  }
}
```

### 4.5 Permissions

- Allowlist the read tools so they don't prompt: `mcp__unizo-ctem-cloud__find_*`, `mcp__unizo-ctem-cloud__get_*`, `mcp__unizo-ctem-cloud__list_*`, `mcp__unizo-ctem-cloud__preview_*`, `mcp__unizo-ctem-cloud__search_all`, `mcp__unizo-ctem-cloud__ping`.
- Write tools are confirmed by hook 2.
- `.claude/settings.local.json` turns off the repo's own `unizo-ctem` and `unizo-ctem-cloud` entries in `.mcp.json`. That's expected, because in this setup the servers come from the installed plugin.

---

## 5. Order of work

1. **Hooks 1, 2 and 5** and the read permissions. These are small, and they close the rule-5 gap and the missing scopes on the client side.
2. **`unizo-ctem-analyst` agent** and the **`exposure-triage` rewrite**.
3. **W1, W2 and W4 skills** and their commands (the most-used workflows, fully covered by the live server).
4. **Hooks 3 and 4** (preview before commit, audit log).
5. **W6, W7 and W8 skills**, written to name the parts the server can't answer yet.
6. **W3 skill**, once `findingsIntake` is switched on.
7. **Optional Stop hook** for vocabulary.

Test each step against dev52 with `/unizo-ctem:unizo-ctem-env use dev52`. The procedures are in `docs/DEV_GUIDE.md`.

---

## 6. Questions for engineering

1. When will token scopes be carried through? Until then rule 2 isn't enforced on the server.
2. Should `move_ticket`, `list_ticket_destinations` and `set_jira_assignee` be removed, as the catalog's section 5 says, or should the catalog be updated?
3. When will these Now tools ship: `find_tickets`, `get_patch_window`, `list_teams`, `get_asset_history`, `get_vulnerability_timeline`, `get_organization_posture` and the findings-intake tools?
4. Will `find_investigations` get the W1 filters (KEV-listed, reaches a crown jewel, owner = me)?
5. Is `reengage_investigation` / `reject_plan` / `select_plan` the intended replacement for `redraft_plan`? If so, the catalog should say so.
6. Does the server expose MCP prompts and resources (`unizo://exposure/...`), as catalog section 4 describes? This hasn't been checked.
