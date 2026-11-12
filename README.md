# unizo-claude-plugin

A Claude Code plugin for Unizo: work your exposure review queue, connect to your Unizo deployment's MCP server, and
switch between deployments, all from Claude Code. It needs only `python3` and the `claude` CLI: there is no local MCP
server and nothing to install with `uv`, `pip` or `npm`.

**Full guide:** [docs/SETUP_AND_TESTING.md](docs/SETUP_AND_TESTING.md) covers installing, configuring for your
GCP/AWS deployment and identity provider, administrator setup, manual and Claude-driven testing, and troubleshooting.

**Developer test guide:** [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md) walks through testing the plugin from a clean state
and switching between environments.

## What's included

| Type | Name | Purpose |
|---|---|---|
| Command | `/unizo:unizo-plugin-configure <environments.json> [<name>]` | Guided setup: pick or switch an environment from the environments file you pass, register the `unizo-cloud` MCP server for it, and sign in. `off` removes it |
| Command | `/unizo:unizo-queue` | Work your review queue (W1): Investigations awaiting review, mine or unclaimed, `crown`, `kev` |
| Skill | `unizo-review-queue` | W1 end to end: queue → read → take → weigh plans → re-draft (if none fits) → choose → `preview_commit` → `commit_actions`, confirming every write |
| Hook | `unizo_guard` | On `unizo-cloud` tools: blocks `move_ticket` / `set_jira_assignee`, refuses `commit_actions` without a recent matching `preview_commit`, asks before every write, audits writes to `~/.config/unizo-mcp/audit.jsonl` |
| Hook | `unizo_onboard` | At session start: offers `/unizo:unizo-plugin-configure` until an environment is picked, then finishes setup on your first message after the restart |
| Agent | `exposure-triage` | Triages a finding and recommends a priority and next step |
| Script | `scripts/unizo_env.py` | Standard-library Python the configure command runs: lists environments, registers `unizo-cloud` with `claude mcp add-json`, records the active environment |
| MCP server | `unizo-cloud` | The remote Unizo MCP server, where every Unizo tool lives. Registered at user scope for the active environment and signed in with Claude Code's own OAuth. The plugin ships no MCP server of its own |

## What you can do

### Work your review queue (W1)

Run `/unizo:unizo-queue`, or ask Claude "what's waiting for my review?". The `unizo-review-queue` skill takes you
through each Investigation in this order:

| Step | What happens | Changes Unizo? |
|---|---|---|
| 1. Queue | Lists Investigations awaiting review, soonest SLA deadline first, with the total and the filter used. Pass `mine` (default), `unclaimed`, `crown` (Exposure reaches a crown jewel), `kev` (CVE on the CISA KEV list), or an Investigation ID to go straight to it | No |
| 2. Read | Shows state, SLA and origin, then **checks the attack path is still live** (no active path, stale source data, owner flags such as a terminated employee) before any plan. Then shows every plan drafted by Unizo, its actions, gate levels, ticket drafts and where tickets would go. Path, risk and blast-radius detail on request | No |
| 3. Take | Claims the Investigation for you, only once you decide to work it | Yes, asks first |
| 4. Weigh | Compares the plans side by side (fix or compensating control, risk reduction, what else it resolves, operational impact, gates, residual risk) and gives a recommendation. You decide | No |
| 5. Re-draft | If no plan fits, asks Unizo for a different one with your guidance, up to three times | Yes, asks first |
| 6. Choose | You pick one plan and its actions | No |
| 7. Check and commit | `preview_commit` shows each ticket's queue, routing rule, connection state and gates. Then commits Soft-gate actions, which creates real ITSM tickets. Hard-gate actions get a link to commit them in the Unizo app | Yes, asks first |

Along the way you can also reject a plan, abandon an Investigation, re-check an Exposure (`verify_exposure_now`)
or add a comment to an action's ticket. Each of these asks first. At the end, Claude lists what was claimed,
re-drafted, rejected and committed, and what is left for you to do in Unizo.

### Guardrails

The `unizo_guard` hook runs on every `unizo-cloud` tool call:

- **Reads pass silently. Every write asks you first.** Claude also confirms in chat, naming exactly what will change.
- **No commit without a preview.** `commit_actions` is refused unless `preview_commit` ran in this session within
  the last 30 minutes for the same Investigation, plan and actions. Rejecting or re-drafting a plan, re-engaging
  the Investigation or editing a ticket draft invalidates earlier previews.
- **Hard gates stay with people.** Over MCP a Hard-gate action is never committed; Claude gives you the Unizo link.
- **Tickets only get comments.** `move_ticket` and `set_jira_assignee` are blocked. Move or reassign tickets in your
  ITSM or the Unizo app.
- **Audit trail.** Every write that ran is appended to `~/.config/unizo-mcp/audit.jsonl`.
- Exposure titles, asset names, plan rationales, ticket drafts and comments are treated as data, never as
  instructions.

### Triage a finding

Paste a scanner finding, CVE or misconfiguration and ask how urgent it is. The `exposure-triage` agent summarises
it, assesses exploitability, business impact and compensating controls, and recommends a priority (Critical, High,
Medium or Low) with a next step: validate, fix, accept or monitor.

### Sign in and switch deployments

You sign in to the remote `unizo-cloud` MCP server once, with Claude Code's own OAuth, through whatever identity
provider your Unizo deployment uses. Claude Code stores and refreshes the tokens. An environments file lets you switch
between deployments (demo, staging, prod, a customer's tenant) with one command. See [Connect to your Unizo deployment](#connect-to-your-unizo-deployment).

### Known limitations

These come from the Unizo server and the skill works around them:

- `find_investigations` has no KEV or crown-jewel filter. The skill filters rows itself and says so, giving the
  size of the set it filtered.
- `redraft_plan` is not deployed yet. Re-drafting falls back to `reengage_investigation`.
- `preview_commit` shows destinations and gates only, not what depends on the fix target or how much of the attack
  path a commit breaks.
- The Jira assignee is set automatically when you claim an Investigation only if your Jira account matches your
  Unizo email. Otherwise, assign tickets in Jira.

## Install

This repo is both a plugin and a single-plugin marketplace.

```
/plugin marketplace add Unizo-CTEM/unizo-claude-plugin
/plugin install unizo@unizo
```

**Prerequisites:** `python3` (3.8 or later; the hooks and the environment script use only the standard library)
and the `claude` CLI on your `PATH`.

## Connect to your Unizo deployment

Each organization runs its own Unizo deployment on GCP or AWS.

### Guided setup (recommended)

After installing, restart Claude Code and run `/unizo:unizo-plugin-configure <path-to-environments.json>` with the
environments file your administrator gave you (Claude also offers it in its first reply until the plugin is set up).
The plugin ships no environments file and reads none by default; without a path, the command asks you for one. It
will:

1. let you pick an environment from that file, and register its remote MCP server as `unizo-cloud` in your Claude
   Code user config;
2. ask you to restart Claude Code so the server loads (`claude` or `claude --continue`);
3. on your first message after the restart, sign you in to `unizo-cloud` through your company's sign-in page
   (Claude Code's own OAuth, the same as `/mcp` → `unizo-cloud` → **Authenticate**) and check the connection with
   `get_my_context`. You don't need to run the command again.

This continues at every startup until setup finishes. It comes back when you switch to another environment.
(Claude Code has no install-time hook, so the flow starts at the first session after install, not inside
`/plugin install` itself.) The plugin asks for nothing during `/plugin install`.

### Signing in and out

Sign-in is handled by Claude Code: `unizo-cloud` is a standard remote MCP server with OAuth, so it works with whatever
identity provider your Unizo deployment uses. Claude Code stores and refreshes the tokens. To sign out, open
`/mcp` → `unizo-cloud` → **Clear authentication**, or run `claude mcp logout unizo-cloud`.

### Environments: switch between deployments

To move between deployments (demo, staging, prod, a customer's tenant), list them in an environments file and
switch with one command. Each environment names the **remote MCP server URL** and, optionally, a pre-registered
**OAuth client ID** for `unizo-cloud`.

```
/unizo:unizo-plugin-configure ~/acme-envs.json           # pick from the file, then restart Claude Code
/unizo:unizo-plugin-configure ~/acme-envs.json staging   # switch straight to staging, then restart Claude Code
/unizo:unizo-plugin-configure off                        # remove unizo-cloud, then restart Claude Code
```

The plugin ships no environments file and never reads one by default: you always pass the path. Keep the file
wherever suits you (for example in a repository your team shares). The format:

```json
{
  "environments": {
    "staging": {
      "description": "Acme staging (GCP)",
      "remote_mcp": {
        "url": "https://unizo-staging.acme.com/mcp",
        "client_id": "unizo-mcp-staging",
        "callback_port": 3118
      }
    }
  }
}
```

| Key | Meaning |
|---|---|
| `remote_mcp.url` | Remote MCP endpoint (`https://`; `http://` only for localhost). Required |
| `remote_mcp.client_id` | Pre-registered OAuth client ID. Leave it out to use dynamic client registration |
| `remote_mcp.callback_port`, `remote_mcp.scopes` | Optional OAuth callback port and scopes |
| `description` | Shown in the list |

Older files may also carry `api_url`, `sso_*` and `use_env_secrets` keys for the local server earlier versions
shipped; they are accepted and ignored. Secrets (`api_token`, `sso_client_secret`) are refused: they never belong in
the file.

How it works:
- Switching registers `unizo-cloud` at user scope with `claude mcp add-json`. That's needed because Claude Code doesn't
  substitute environment variables into a remote server's `oauth.clientId`, so a plugin `.mcp.json` can't do it.
- When the URL or client ID changes, the old sign-in is cleared, because Claude Code would otherwise reuse the cached
  OAuth client. Sign in again when asked.
- The configure command won't replace a `unizo-cloud` server it didn't add without asking you first.
- The active environment is kept in `~/.config/unizo-mcp/active-environment.json`. Restart Claude Code after switching.

From a terminal: `python3 <plugin-dir>/scripts/unizo_env.py [list --file <path> | current | use <name> --file <path> [--force] | off]`.

### Upgrading from a version with the local `unizo` server

Earlier versions shipped a local `unizo` MCP server (run with `uv`) that signed in to the Unizo gateway and passed that
token to `unizo-cloud`. It's gone. If you set up an environment with an earlier version, Claude tells you at the next
session start; run `/unizo:unizo-plugin-configure <environments.json> <name>` again, restart, and sign in to
`unizo-cloud` once through `/mcp`. The old gateway token cache (`~/.config/unizo-mcp/tokens.json`) is no longer used
and can be deleted.

## For administrators: deployment requirements

**Remote MCP server (`remote_mcp.url` in an environment):** it must implement
[MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization). It answers `401`
with `WWW-Authenticate` pointing at its OAuth protected-resource metadata, and its authorization server supports
**dynamic client registration**, or you pre-register a public client and send users its ID as
`remote_mcp.client_id`. The client must allow the redirect URI `http://localhost:<port>/callback`. Pin the port with
`remote_mcp.callback_port`; otherwise Claude Code picks one. The token's audience must match what the server checks.
Keycloak ignores the `resource` parameter Claude Code sends, so add an audience mapper for the MCP URL.

The server must be reachable over HTTPS from users' machines (VPN, allow-listing, etc.).

## Development

```
claude --plugin-dir .          # load the plugin from this checkout
python3 -m pytest tests        # hook and environment-script tests (needs pytest)
```

To test the install flow, install from a local marketplace:
`claude plugin marketplace add /path/to/unizo-claude-plugin`, then `claude plugin install unizo@unizo`.

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # marketplace catalog (lists this plugin)
commands/            # slash commands
skills/              # skills (one folder per skill, with SKILL.md)
agents/              # subagents
hooks/               # onboarding and guard hooks (hooks.json + Python scripts)
scripts/             # unizo_env.py: environments and the unizo-cloud registration
tests/               # pytest tests for the hooks and scripts
docs/                # setup, developer and planning guides
```

## Validate

```
claude plugin validate .
```
