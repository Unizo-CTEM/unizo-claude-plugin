# ctem-claude-plugin

A Claude Code plugin for Unizo CTEM (Continuous Threat Exposure Management).

**Full guide:** [docs/SETUP_AND_TESTING.md](docs/SETUP_AND_TESTING.md) covers installing, configuring for your
GCP/AWS deployment and identity provider, administrator setup, manual and Claude-driven testing, and troubleshooting.

**Developer test guide:** [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md) walks through testing the plugin from a clean state
and switching between environments.

## What's included

| Type | Name | Purpose |
|---|---|---|
| Command | `/unizo-ctem:unizo-ctem-setup` | Check the connection to your CTEM deployment and walk through setup or SSO sign-in |
| Command | `/unizo-ctem:unizo-ctem-env` | List environments (demo, staging, prod, ...) and switch between them |
| Command | `/unizo-ctem:unizo-ctem-hello` | Check that the plugin is installed and list what it provides |
| Command | `/unizo-ctem:queue` | Work your review queue (W1): Investigations awaiting review, mine or unclaimed, `crown`, `kev` |
| Skill | `unizo-ctem-basics` | Explains CTEM concepts and the five-stage cycle |
| Skill | `unizo-ctem-review-queue` | W1 end to end: queue → claim → review plans → `preview_commit` → `commit_actions`, confirming every write |
| Hook | `unizo_ctem_guard` | On `unizo-ctem-cloud` tools: blocks `move_ticket` / `set_jira_assignee`, refuses `commit_actions` without a recent matching `preview_commit`, asks before every write, audits writes to `~/.config/unizo-ctem-mcp/audit.jsonl` |
| Agent | `exposure-triage` | Triages a finding and recommends a priority and next step |
| MCP server | `unizo-ctem` | Local server (stdio) that calls your CTEM gateway, with SSO sign-in |
| MCP server | `unizo-ctem-cloud` | Remote CTEM MCP server, registered by the active environment (`/unizo-ctem:unizo-ctem-env use demo` for `https://demo.unizo.ai/mcp`) |

## Install

This repo is both a plugin and a single-plugin marketplace.

```
/plugin marketplace add Unizo-CTEM/ctem-claude-plugin
/plugin install unizo-ctem@unizo-ctem
```

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be on your `PATH` (`pipx install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). The local MCP server runs with it.

## Connect to your CTEM deployment

Each organization runs its own CTEM deployment on GCP or AWS. Point the plugin at yours:

1. Run `/plugin configure unizo-ctem@unizo-ctem` (Claude Code also prompts when you enable the plugin).
2. Fill in the options below. Your administrator can supply the values.
3. Restart Claude Code, then run `/unizo-ctem:unizo-ctem-setup` to check the connection and sign in.

To configure from a script, for example when rolling out to a team:

```
echo '{"api_url":"https://ctem.acme.com","sso_issuer":"https://acme.okta.com/oauth2/default","sso_client_id":"0oa..."}' \
  | claude plugin configure unizo-ctem@unizo-ctem --values-stdin
```

| Option | Required | Meaning |
|---|---|---|
| `api_url` | yes | Base URL of your CTEM gateway, e.g. `https://ctem.acme.com` |
| `api_token` | no | Static bearer token (service accounts, CI). If set, it takes precedence over SSO. Stored as a secret |
| `sso_issuer` | for SSO | OIDC issuer URL; `<issuer>/.well-known/openid-configuration` must exist |
| `sso_client_id` | for SSO | Client ID of the native/public app registered for this plugin |
| `sso_client_secret` | no | Only if your IdP requires a secret for native apps. Stored as a secret |
| `sso_scopes` | no | Default `openid profile email offline_access` |
| `sso_audience` | no | Sent as `audience` (Auth0, some Okta authorization servers) |
| `sso_token_type` | no | `access` (default) or `id`: the token your gateway expects |
| `sso_redirect_port` | no | Local callback port, default `8765` |

Secrets marked sensitive are kept in Claude Code's secure storage, not in its settings files.

### Signing in with SSO

The plugin works with any OIDC provider: Okta, Microsoft Entra ID, Auth0, Google Workspace, AWS Cognito and others.
Ask Claude to "sign in to CTEM", or run `/unizo-ctem:unizo-ctem-setup`. Your browser opens at your company's sign-in page.
Tokens are cached in `~/.config/unizo-ctem-mcp/tokens.json` (readable only by you) and refresh automatically, so you sign
in again only when your IdP ends the session. Tokens are kept per issuer and client ID, so people who work with more
than one deployment don't get their sessions mixed up.

To sign out, ask Claude to "sign out of CTEM" (the `unizo_ctem_logout` tool).

### Environments: switch between deployments

To move between deployments (demo, staging, prod, a customer's tenant), list them in an environments file and
switch with one command. Each environment sets the gateway and SSO values for the local `unizo-ctem` server, plus the
**remote MCP server URL and OAuth client ID** for `unizo-ctem-cloud`.

```
/unizo-ctem:unizo-ctem-env                 # list; * marks the active one
/unizo-ctem:unizo-ctem-env use staging     # switch, then restart Claude Code
/unizo-ctem:unizo-ctem-env off             # back to the /plugin configure options
```

The plugin ships [`environments.json`](environments.json) with `demo`. Add your own in
`~/.config/unizo-ctem-mcp/environments.json`, or in the file `$UNIZO_CTEM_ENVIRONMENTS_FILE` names, for example a file your team
keeps in a repository. An entry there replaces a shipped entry with the same name. See
[`environments.example.json`](environments.example.json):

```json
{
  "environments": {
    "staging": {
      "description": "Acme staging (GCP)",
      "api_url": "https://ctem-staging.acme.com",
      "sso_issuer": "https://acme.okta.com/oauth2/default",
      "sso_client_id": "0oa-staging-client",
      "remote_mcp": {
        "url": "https://ctem-staging.acme.com/mcp",
        "client_id": "ctem-mcp-staging",
        "callback_port": 3118
      }
    }
  }
}
```

| Key | Meaning |
|---|---|
| `api_url`, `sso_issuer`, `sso_client_id`, `sso_scopes`, `sso_audience`, `sso_token_type`, `sso_redirect_port` | Same as the plugin options above |
| `remote_mcp.url` | Remote MCP endpoint (`https://`; `http://` only for localhost) |
| `remote_mcp.client_id` | Pre-registered OAuth client ID. Leave it out to use dynamic client registration |
| `remote_mcp.callback_port`, `remote_mcp.scopes` | Optional OAuth callback port and scopes for the remote server |
| `use_plugin_secrets` | `true` to use the `api_token` / `sso_client_secret` set in `/plugin configure` with this environment |
| `description` | Shown in the list |

How it works:
- While an environment is active, its values **replace** every plugin option: keys it leaves out fall back to the
  defaults, not to whatever was configured before. Nothing leaks from one deployment into the next.
- Secrets aren't allowed in the file. An environment uses the token or client secret from `/plugin configure` only
  if it sets `"use_plugin_secrets": true`, so a token for one deployment is never sent to another.
- `use` registers `unizo-ctem-cloud` at user scope with `claude mcp add-json`. That's needed because Claude Code doesn't
  substitute plugin options or environment variables into a remote server's `oauth.clientId`. When the URL or client
  ID changes, the old sign-in is cleared, because Claude Code would otherwise reuse the cached OAuth client. Sign in
  again from `/mcp` → `unizo-ctem-cloud` → **Authenticate**.
- The active environment is kept in `~/.config/unizo-ctem-mcp/active-environment.json`. Restart Claude Code after switching.

From a terminal: `uv run --project <plugin-dir>/mcp-server unizo-ctem-mcp env [list | current | use <name> | off]`.

## For administrators: deployment requirements

**Gateway (`api_url`)**
- Reachable over HTTPS from users' machines (VPN, allow-listing, etc.).
- Accepts `Authorization: Bearer <token>`, validating SSO tokens against your IdP (issuer, audience, signature).
- Returns `401` for missing, expired or invalid tokens. The plugin then refreshes the token once and retries.
- Serves `GET /health`, which `/unizo-ctem:unizo-ctem-setup` uses for the connectivity check.

**Identity provider:** register one *native/public* application for the plugin:
- Grant type: authorization code with PKCE. Allow refresh tokens so users stay signed in.
- Redirect URI: `http://localhost:8765/callback`, or the port you distribute as `sso_redirect_port`.
- If the gateway validates access tokens, make sure the IdP issues JWT access tokens for the gateway's audience
  (set `sso_audience` if your IdP needs it). Otherwise set `sso_token_type` to `id`.

**Remote MCP server (optional, `remote_mcp.url` in an environment):** it must implement
[MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization). It answers `401`
with `WWW-Authenticate` pointing at its OAuth protected-resource metadata, and its authorization server supports
**dynamic client registration**, or you pre-register a public client and send users its ID as
`remote_mcp.client_id`. The client must allow the redirect URI `http://localhost:<port>/callback`. Pin the port with
`remote_mcp.callback_port`; otherwise Claude Code picks one. The token's audience must match what the server checks.
Keycloak ignores the `resource` parameter Claude Code sends, so add an audience mapper for the MCP URL.

## Development

```
claude --plugin-dir .                      # load the plugin from this checkout
cd mcp-server && uv run pytest             # MCP server tests
```

### Testing against a fake deployment

`mcp-server/tests/e2e/fake_stack.py` runs a fake OIDC identity provider and CTEM gateway on localhost. The IdP
signs in `analyst@example.com` instantly but still enforces the client ID, redirect URI and PKCE like a real one.

```
python3 mcp-server/tests/e2e/fake_stack.py --access-ttl 70     # 70s tokens: refresh kicks in after ~10s
```

Point the installed plugin at it (`/plugin configure unizo-ctem@unizo-ctem`):
`api_url` = `http://127.0.0.1:9401`, `sso_issuer` = `http://127.0.0.1:9400`, `sso_client_id` = `ctem-plugin-test`.
Then run `/unizo-ctem:unizo-ctem-setup`. Other things to try:

- Revoke every session: `curl -X POST 127.0.0.1:9400/admin/revoke-all`, then ask Claude to check the connection.
- See what the gateway received: `curl 127.0.0.1:9401/admin/stats`.
- Test the "no browser" path: start Claude Code with `BROWSER="/usr/bin/true %s"` and the sign-in URL is shown
  instead of opened. (`/usr/bin/false` doesn't work: Python then falls back to the default browser.)

Plugins loaded with `--plugin-dir` can't be configured, so install from a local marketplace to test settings:
`claude plugin marketplace add /path/to/ctem-claude-plugin`, then `claude plugin install unizo-ctem@unizo-ctem`.

Outside the plugin, the MCP server reads the `CTEM_*` environment variables directly (see
`mcp-server/src/unizo_ctem_mcp/config.py`). `uv run --project mcp-server unizo-ctem-mcp login | logout | whoami` signs in
from a terminal and uses the same token cache.

The root `.mcp.json` uses `${user_config.*}` placeholders that only resolve when Claude Code loads it as a plugin.
When you open this repo directly, disable its project-scoped copies (`disabledMcpjsonServers` in
`.claude/settings.local.json`).

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # marketplace catalog (lists this plugin)
commands/            # slash commands
skills/              # skills (one folder per skill, with SKILL.md)
agents/              # subagents
```

## Validate

```
claude plugin validate .
```
