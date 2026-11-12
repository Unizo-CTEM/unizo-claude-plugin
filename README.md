# unizo-claude-plugin

A Claude Code plugin for Unizo: work your exposure review queue, connect to your Unizo deployment's MCP server, and
switch between deployments, all from Claude Code. It needs only `python3` and the `claude` CLI: there is no local MCP
server and nothing to install with `uv`, `pip` or `npm`.

> **Renamed:** this plugin was formerly `unizo-ctem` (repo `ctem-claude-plugin`). See
> [Upgrading from unizo-ctem](#upgrading-from-unizo-ctem) if you had the old version installed.

**Full guide:** [docs/SETUP_AND_TESTING.md](docs/SETUP_AND_TESTING.md) covers installing, configuring for your
GCP/AWS deployment and identity provider, administrator setup, manual and Claude-driven testing, and troubleshooting.

**Developer test guide:** [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md) walks through testing the plugin from a clean state
and switching between environments.

## What's included

| Type | Name | Purpose |
|---|---|---|
| Command | `/unizo:unizo-plugin-configure <environments.json> [<name>]` | Guided setup: pick or switch an environment from the environments file you pass, register the `unizo-cloud` MCP server for it, and sign in. `off` removes it |
| Command | `/unizo:unizo-queue` | Work your review queue (W1): Investigations awaiting review, mine or unclaimed, `crown`, `kev` |
| Skill | `unizo-review-queue` | W1 end to end: queue → claim → review plans → `preview_commit` → `commit_actions`, confirming every write |
| Hook | `unizo_guard` | On `unizo-cloud` tools: blocks `move_ticket` / `set_jira_assignee`, refuses `commit_actions` without a recent matching `preview_commit`, asks before every write, audits writes to `~/.config/unizo-mcp/audit.jsonl` |
| Hook | `unizo_onboard` | At session start: offers `/unizo:unizo-plugin-configure` until an environment is picked, then finishes setup on your first message after the restart |
| Agent | `exposure-triage` | Triages a finding and recommends a priority and next step |
| Script | `scripts/unizo_env.py` | Standard-library Python the configure command runs: lists environments, registers `unizo-cloud` with `claude mcp add-json`, records the active environment |
| MCP server | `unizo-cloud` | The remote Unizo MCP server, where every Unizo tool lives. Registered at user scope for the active environment and signed in with Claude Code's own OAuth. The plugin ships no MCP server of its own |

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

## Upgrading from unizo-ctem

Everything named `ctem` was renamed. If you had the old plugin installed:

| Old | New |
|---|---|
| Plugin `unizo-ctem@unizo-ctem`, repo `Unizo-CTEM/ctem-claude-plugin` | `unizo@unizo`, `Unizo-CTEM/unizo-claude-plugin` |
| `/unizo-ctem:unizo-ctem-plugin-configure`, `/unizo-ctem:unizo-ctem-queue` | `/unizo:unizo-plugin-configure`, `/unizo:unizo-queue` |
| Skill `unizo-ctem-review-queue` | `unizo-review-queue` |
| MCP servers `unizo-ctem`, `unizo-ctem-cloud` | `unizo`, `unizo-cloud` |
| `UNIZO_CTEM_*` variables | `UNIZO_*` |
| `~/.config/unizo-ctem-mcp/` | `~/.config/unizo-mcp/` |

1. Uninstall `unizo-ctem` and remove its marketplace, then install as above.
2. Remove the old remote server: `claude mcp remove unizo-ctem-cloud -s user`.
3. Rename any `UNIZO_CTEM_*` variables you export to `UNIZO_*`.
4. Restart Claude Code and run `/unizo:unizo-plugin-configure <environments.json>`. To keep your saved sign-in
   instead, copy `~/.config/unizo-ctem-mcp/` to `~/.config/unizo-mcp/` first.
