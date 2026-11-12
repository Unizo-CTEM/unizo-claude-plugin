# Unizo plugin: setup and testing guide

This guide covers installing the Unizo plugin for Claude Code, connecting it to your organization's Unizo
deployment (GCP or AWS), and testing it, with and without Claude.

| If you are... | Read |
|---|---|
| A user connecting to your company's deployment | [1. Install](#1-install), [2. Configure](#2-configure), [3. Verify](#3-verify-the-setup) |
| An administrator preparing a deployment or IdP | [4. Administrator setup](#4-administrator-setup) |
| A developer or QA engineer testing the plugin | [5. Testing](#5-testing) |
| Stuck | [6. Troubleshooting](#6-troubleshooting) |

---

## How the plugin connects

```
Claude Code
 ├── unizo  (local MCP server, stdio, started with uv)
 │     ├── SSO sign-in  ──►  your identity provider (Okta, Entra ID, Auth0, Google, Cognito, ...)
 │     └── HTTPS + Bearer token  ──►  your Unizo gateway  (api_url)
 └── unizo-cloud  (remote MCP server, HTTP)  ──►  remote_mcp.url of the active environment

 <your environments.json>  ──►  /unizo:unizo-plugin-configure <environments.json> [<name>]  picks the environment for both
```

- **`unizo`** runs on your machine. It signs you in through your company SSO (or uses a static API token) and calls
  your Unizo gateway. Tools: `unizo_status`, `unizo_login`, `unizo_logout`.
- **`unizo-cloud`** connects to the remote Unizo MCP server of the active environment (`demo` →
  `https://demo.unizo.ai/mcp`). Claude Code handles its sign-in.
- **Environments** ([2.7](#27-environments-switching-between-deployments)) bundle the gateway, SSO and remote
  server URL + client ID per deployment, so you can switch with one command.
- **Commands:** `/unizo:unizo-plugin-configure` (pick or switch an environment, sign in, check the connection) and
  `/unizo:unizo-queue` (work your review queue). **Skill:** `unizo-review-queue`. **Agent:** `exposure-triage`.

---

## 1. Install

### Prerequisites

| Requirement | Check | Install |
|---|---|---|
| Claude Code | `claude --version` | <https://code.claude.com> |
| `uv` (runs the local MCP server) | `uv --version` | `pipx install uv`, or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| HTTPS access to your Unizo gateway | `curl -sI https://<your-gateway>/health` | VPN or allow-listing, per your IT team |

`uv` downloads Python 3.12+ automatically if your machine doesn't have it. On macOS, Homebrew may build `uv` from
source, which can take a very long time; `pipx` or the install script uses a prebuilt binary.

Make sure `uv` is on the `PATH` that Claude Code sees: open a new terminal and run `command -v uv`.

### Install from the marketplace

In Claude Code:

```
/plugin marketplace add Unizo-CTEM/ctem-claude-plugin
/plugin install unizo@unizo
```

Or from a terminal:

```
claude plugin marketplace add Unizo-CTEM/ctem-claude-plugin
claude plugin install unizo@unizo
```

### Install from a local folder (development, QA, air-gapped)

```
claude plugin marketplace add /path/to/unizo-claude-plugin
claude plugin install unizo@unizo
```

> `claude --plugin-dir /path/to/unizo-claude-plugin` also loads the plugin, but plugins loaded that way **can't be
> configured**, so the `unizo` server never starts. Use the local marketplace whenever you need the settings.

---

## 2. Configure

### 2.1 Get these values from your administrator

- **Unizo API URL**: always required.
- **Either** an **API token** (service accounts, CI) **or** the **SSO issuer URL** and **SSO client ID**.
- Optionally: SSO audience, scopes, token type, callback port, and the remote Unizo MCP URL.

### 2.2 With an environment (recommended)

The plugin asks for nothing during `/plugin install`. Run `/unizo:unizo-plugin-configure <path-to-environments.json>` after
installing (there is no default file; without a path it asks for one): it lets you pick from the file, switches to an environment, and signs you in ([2.7](#27-environments-switching-between-deployments)).

### 2.3 With environment variables (no environments file)

Export the settings before starting Claude Code. The `unizo` server inherits them. **Restart Claude Code** after
changing them.

```bash
export UNIZO_API_URL=https://unizo.acme.com
export UNIZO_OIDC_ISSUER=https://acme.okta.com/oauth2/default
export UNIZO_OIDC_CLIENT_ID=0oa1b2c3d4EXAMPLE
claude
```

Don't put secrets (`UNIZO_API_TOKEN`, `UNIZO_OIDC_CLIENT_SECRET`) in files that get committed or shared.
Load them from your secret manager instead.

### 2.4 Option reference

| Environment key | Variable | Required | Default | Description |
|---|---|---|---|---|
| `api_url` | `UNIZO_API_URL` | yes, unless you use an environment | | Base URL of your Unizo gateway, e.g. `https://unizo.acme.com`. |
| (secret, not allowed in the file) | `UNIZO_API_TOKEN` | no | | Static bearer token. **If set, it takes precedence over SSO.** |
| `sso_issuer` | `UNIZO_OIDC_ISSUER` | for SSO | | OIDC issuer URL. `<issuer>/.well-known/openid-configuration` must exist. |
| `sso_client_id` | `UNIZO_OIDC_CLIENT_ID` | for SSO | | Client ID of the native/public app registered for the plugin. |
| (secret, not allowed in the file) | `UNIZO_OIDC_CLIENT_SECRET` | no | | Only if your IdP requires a secret for native apps (e.g. Google). |
| `sso_scopes` | `UNIZO_OIDC_SCOPES` | no | `openid profile email offline_access` | Space-separated. `offline_access` requests a refresh token. |
| `sso_audience` | `UNIZO_OIDC_AUDIENCE` | no | | Sent as the `audience` parameter (Auth0, some Okta setups). |
| `sso_token_type` | `UNIZO_OIDC_TOKEN_TYPE` | no | `access` | Which token is sent to the gateway: `access` or `id`. |
| `sso_redirect_port` | `UNIZO_OIDC_REDIRECT_PORT` | no | `8765` | Local port for the sign-in callback. Must match the registered redirect URI. |

**Where values are stored:** secrets live only in your shell environment. SSO tokens are cached in `~/.config/unizo-mcp/tokens.json`, which only you
can read (mode `0600`). They're kept separately for each issuer and client ID.

### 2.5 Identity provider examples

These are starting points. Confirm the exact values with your IdP administrator.

| IdP | `sso_issuer` | Notes |
|---|---|---|
| Okta | `https://<org>.okta.com/oauth2/default` (custom authorization server) | Native app, Authorization Code + Refresh Token, PKCE. Use the custom authorization server if the gateway validates access tokens. |
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` | Register a "Mobile and desktop" redirect URI. To get an access token for the gateway, add its scope to `sso_scopes`, e.g. `openid profile email offline_access api://<gateway-app-id>/access`. |
| Auth0 | `https://<tenant>.auth0.com/` | Native application. Set `sso_audience` to the gateway API identifier, or you get a token the gateway can't validate. |
| Google Workspace | `https://accounts.google.com` | "Desktop app" OAuth client: Google issues a client secret, so set `sso_client_secret`. Use `sso_scopes` = `openid email profile` and `sso_token_type` = `id`, because Google access tokens aren't JWTs. Expect to sign in again when the ID token expires. |
| AWS Cognito | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>` | App client **without** a secret, hosted UI/domain enabled. Use `sso_scopes` = `openid email profile` (Cognito issues refresh tokens without `offline_access`). |

### 2.6 Remote MCP server (`unizo-cloud`)

The remote server comes from the active environment's `remote_mcp` block ([2.7](#27-environments-switching-between-deployments)).
If no environment is active, there's no remote server. With a file that defines `demo`:

```
/unizo:unizo-plugin-configure <environments.json> demo
```

`demo` points at `https://demo.unizo.ai/mcp`. Its sign-in uses the Keycloak realm `https://demo.unizo.ai/realms/ctem`
with the pre-registered public client `dW5pem8tbWNwLWNsaWVudA==`.

1. Restart Claude Code after switching.
2. Run `/mcp`. `unizo-cloud` shows **Needs authentication**. Select it and choose **Authenticate**. A browser window
   opens at the sign-in page. After you sign in, `unizo-cloud` shows as connected and its tools become available.

Why the plugin doesn't ship `unizo-cloud` in its `.mcp.json`: Claude Code reads a remote server's `oauth.clientId`
literally. It doesn't substitute `${ENV_VAR}` there (verified with Claude Code 2.1.318), so a
variable can't set the client ID. `unizo-mcp env use` (which setup runs) registers the server at user scope with
`claude mcp add-json`, which takes a literal client ID.

### 2.7 Environments: switching between deployments

An environment names one deployment: the gateway and SSO settings for the local `unizo` server, and the URL and OAuth
client ID of the remote MCP server. In Claude Code, `/unizo:unizo-plugin-configure <environments.json>` (pick from the
file) or `/unizo:unizo-plugin-configure <environments.json> <name>` picks one. From a terminal, run
`uv run --project <plugin-dir>/mcp-server unizo-mcp env ...`:

| Command | Does |
|---|---|
| `env list --file <path>` | Lists the file's environments; `*` marks the active one |
| `env use <name> --file <path>` | Makes `<name>` active and registers its remote server as `unizo-cloud` |
| `env current` | Shows the active environment and where it's defined |
| `env off` | Goes back to the `UNIZO_*` environment variables and removes the `unizo-cloud` it added |

Restart Claude Code after `use` or `off`.

**Files**: there is no default. The plugin ships no environments file and never reads one unless you pass its path
(`--file` is required for `list` and `use`). The active environment remembers its file's path and is read from that
file only, so keep the file in place while it's in use.

```json
{
  "environments": {
    "staging": {
      "description": "Acme staging (GCP)",
      "api_url": "https://unizo-staging.acme.com",
      "sso_issuer": "https://acme.okta.com/oauth2/default",
      "sso_client_id": "0oa-staging-client",
      "sso_audience": "api://unizo",
      "remote_mcp": {
        "url": "https://unizo-staging.acme.com/mcp",
        "client_id": "unizo-mcp-staging",
        "callback_port": 3118
      }
    },
    "prod": {
      "api_url": "https://unizo.acme.com",
      "sso_issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
      "sso_client_id": "11111111-2222-3333-4444-555555555555",
      "remote_mcp": { "url": "https://unizo.acme.com/mcp", "client_id": "unizo-mcp-prod" }
    }
  }
}
```


| Key | Meaning |
|---|---|
| `api_url`, `sso_issuer`, `sso_client_id`, `sso_scopes`, `sso_audience`, `sso_token_type`, `sso_redirect_port` | As in [2.4](#24-option-reference) |
| `remote_mcp.url` | **Required in `remote_mcp`.** `https://` (`http://` only for localhost) |
| `remote_mcp.client_id` | Pre-registered OAuth client ID. Leave it out to use dynamic client registration |
| `remote_mcp.callback_port` | Fixed OAuth callback port, to match a registered `http://localhost:<port>/callback` |
| `remote_mcp.scopes` | Space-separated scopes to request instead of the server's advertised ones |
| `remote_mcp: null` | No remote server for this environment |
| `use_env_secrets` | `true` to use `UNIZO_API_TOKEN` / `UNIZO_OIDC_CLIENT_SECRET` from the environment (default `false`; the old name `use_plugin_secrets` still works) |
| `description` | Shown in the list |

**Rules:**
- An active environment **replaces** every `UNIZO_*` variable. Keys it leaves out use the defaults, never a value
  configured earlier, so nothing leaks from one deployment into the next.
- Secrets (`api_token`, `sso_client_secret`) are rejected in environments files. An environment uses the ones from
  the environment variables only with `"use_env_secrets": true`, so a token for one deployment is never sent to
  another.
- When the remote URL or client ID changes, `use` signs `unizo-cloud` out. Claude Code otherwise reuses its cached
  OAuth client registration, and that wins over a new client ID. Sign in again from `/mcp`.
- `use` refuses to replace a user-scope `unizo-cloud` it didn't add, unless you pass `--force`.
- Gateway SSO tokens are cached per issuer and client ID, so switching back doesn't need a new gateway sign-in.
- The active environment is kept in `~/.config/unizo-mcp/active-environment.json`. `unizo_status` reports it as
  `environment`. If that environment disappears from the files, the server falls back to the `UNIZO_*` variables and
  lists the problem in `config_problems`.

---

## 3. Verify the setup

1. **Is the server running?** In a terminal:

   ```
   claude mcp list | grep plugin:unizo
   ```

   You should see `plugin:unizo:unizo: ... ✔ Connected`. If `plugin:unizo:unizo` is missing, `api_url` isn't set.

2. **Check the connection and sign in.** In Claude Code, run:

   ```
   /unizo:unizo-plugin-configure
   ```

   Claude checks the connection. If you're using SSO and aren't signed in, it starts the sign-in: a browser tab
   opens at your company's sign-in page. When the tab says "Logged in to Unizo", go back to Claude.

3. **Expected result:** Claude reports your API URL, `auth_mode` (`sso` or `static-token`), who you're signed in
   as, and **reachable: true**.

Everyday use: just ask, e.g. "sign in to Unizo", "check my Unizo connection", "sign out of Unizo".

---

## 4. Administrator setup

### 4.1 Unizo gateway (`api_url`)

- [ ] Reachable over HTTPS from users' machines.
- [ ] Accepts `Authorization: Bearer <token>` and validates SSO tokens: signature (JWKS), `iss`, `aud`, expiry.
- [ ] Returns **401** for missing, expired or invalid tokens. The plugin refreshes the token once and retries.
- [ ] Serves `GET /health`, used by `unizo_status` and `/unizo:unizo-plugin-configure`. Any 2xx counts as healthy.

### 4.2 Identity provider app registration

- [ ] One **native/public** application (no secret, unless your IdP requires one).
- [ ] Grant type **Authorization Code with PKCE (S256)**, plus **Refresh Token**.
- [ ] Redirect URI exactly `http://localhost:8765/callback`, or `http://localhost:<port>/callback` if you
      distribute a different `sso_redirect_port`.
- [ ] If the gateway validates access tokens: the IdP issues **JWT** access tokens for the gateway's audience. Set
      `sso_audience` or add an API scope as your IdP requires. Otherwise distribute `sso_token_type` = `id`.
- [ ] Users or groups are assigned to the app.

### 4.3 Remote MCP server (`remote_mcp` in an environment)

- [ ] Implements [MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization):
      unauthenticated requests get `401` with a `WWW-Authenticate` header that points to the OAuth
      protected-resource metadata.
- [ ] Either its authorization server supports **dynamic client registration**, or you register a public client
      with PKCE and send users its ID as `remote_mcp.client_id`.
- [ ] The client allows the redirect URI `http://localhost:<port>/callback`. Use a wildcard port, or pin it with
      `remote_mcp.callback_port`.
- [ ] Access tokens carry the audience the server checks. Claude Code requests them with
      `resource=<remote_mcp.url>`, but **Keycloak ignores `resource`**: add an *Audience* mapper for the MCP URL
      to a default client scope. Otherwise sign-in succeeds and the server answers `401 invalid_token`
      ("rejected them on reconnect").
- [ ] For Keycloak with dynamic registration: the realm's client registration policies must allow anonymous
      registration from users' machines (the default "Trusted Hosts" policy rejects it).

### 4.4 Values to send your users

Send an environments file. Users save it anywhere (or use a shared copy) and pass its path to the configure command:

```json
{
  "environments": {
    "acme": {
      "description": "Acme production",
      "api_url": "https://unizo.acme.com",
      "sso_issuer": "https://acme.okta.com/oauth2/default",
      "sso_client_id": "0oa1b2c3d4EXAMPLE",
      "remote_mcp": { "url": "https://unizo.acme.com/mcp", "client_id": "unizo-mcp-acme" }
    }
  }
}
```

Then they run `/unizo:unizo-plugin-configure <path-to-the-file> acme` and restart Claude Code. Without environments, `UNIZO_*` environment
variables still work ([2.3](#23-with-environment-variables-no-environments-file)). That route has no remote server.

---

## 5. Testing

The fastest checks come first. Steps 5.1–5.3 need no Claude usage and no real deployment.

| Level | What it proves | Needs |
|---|---|---|
| [5.1 Automated tests](#51-automated-tests) | Logic: PKCE, token cache, refresh, retry, config parsing, MCP tools | `uv` |
| [5.2 Fake deployment](#52-the-fake-deployment) | Real HTTP sign-in and gateway calls end to end | `uv`, Python 3 |
| [5.3 Manual test without Claude](#53-manual-test-without-claude) | The server works on its own, through MCP | 5.2 |
| [5.4 Interactive test in Claude Code](#54-interactive-test-in-claude-code) | Install, configure, and real user flows | Claude Code |
| [5.5 Headless smoke test](#55-headless-smoke-test-through-claude) | Repeatable Claude-driven regression run | Claude Code (uses your account) |
| [5.6 Real deployment acceptance](#56-acceptance-test-against-a-real-deployment) | Works with the customer's IdP and gateway | Real values |

All commands below run from the repository root.

### 5.1 Automated tests

```bash
cd mcp-server
uv sync --extra dev
uv run pytest -q          # expect: all tests pass
cd ..
claude plugin validate .  # expect: ✔ Validation passed
```

| File | Covers |
|---|---|
| `tests/test_server.py` | `unizo_status` with no config, a static token, and an auth failure |
| `tests/test_auth.py` | PKCE sign-in through a real localhost callback, forged `state`, IdP errors, refresh, revoked refresh, ID-token mode, gateway 401 → refresh → retry, static token precedence, login/status/logout tools |
| `tests/test_config.py` | Defaults when options are empty, option parsing, invalid values reported (not fatal) |

### 5.2 The fake deployment

`mcp-server/tests/e2e/fake_stack.py` runs a fake OIDC identity provider and a fake Unizo gateway on localhost. The IdP
signs in `analyst@example.com` instantly, but it still enforces the client ID, redirect URI and PKCE like a real one.

```bash
python3 mcp-server/tests/e2e/fake_stack.py --access-ttl 70
```

| Endpoint | Purpose |
|---|---|
| `http://127.0.0.1:9400` | Fake IdP (issuer). Client ID `unizo-plugin-test` |
| `http://127.0.0.1:9401/health` | 200 with a valid token, 401 without |
| `POST http://127.0.0.1:9400/admin/revoke-all` | Revoke every session (tests re-login) |
| `GET http://127.0.0.1:9401/admin/stats` | Counts of logins, refreshes, and gateway 200s/401s |

`--access-ttl 70` makes tokens go stale about 10 seconds after sign-in (the plugin refreshes 60 seconds before
expiry), so you can watch a refresh happen. Leave the stack running in its own terminal; stop it with Ctrl+C.

### 5.3 Manual test without Claude

In a second terminal, point the server at the fake deployment. Use a separate token cache, so your real one isn't
touched:

```bash
export UNIZO_API_URL=http://127.0.0.1:9401
export UNIZO_OIDC_ISSUER=http://127.0.0.1:9400
export UNIZO_OIDC_CLIENT_ID=unizo-plugin-test
export UNIZO_TOKEN_CACHE=/tmp/unizo-test-tokens.json
```

**Terminal sign-in (CLI):**

```bash
uv run --project mcp-server unizo-mcp whoami    # {'logged_in': False}
uv run --project mcp-server unizo-mcp login     # opens a browser tab, then prints "Logged in as analyst@example.com."
uv run --project mcp-server unizo-mcp whoami    # logged_in: True, subject, expires_at
ls -l /tmp/unizo-test-tokens.json               # -rw-------
```

**Call the MCP tools directly** (through a real MCP client session):

```bash
H=mcp-server/tests/e2e/call_tool.py
uv run --project mcp-server python $H --list              # unizo_status, unizo_login, unizo_logout
uv run --project mcp-server python $H                     # unizo_status -> "reachable": true
uv run --project mcp-server python $H unizo_logout
uv run --project mcp-server python $H unizo_login '{"wait_seconds": 30}'
```

**Scenarios to check:**

| # | Do | Expect |
|---|---|---|
| M1 | `unizo_status` while signed out | `reachable: false`, detail says to call `unizo_login`, `sso.logged_in: false` |
| M2 | `unizo_login` | `logged_in: true`, `subject: analyst@example.com` |
| M3 | Wait 12 s, then `unizo_status` | `reachable: true`; `/admin/stats` shows `refreshes` went up by 1 |
| M4 | `curl -X POST 127.0.0.1:9400/admin/revoke-all`, then `unizo_status` | `reachable: false`, `sso.logged_in: false` (cache cleared) |
| M5 | `export BROWSER="/usr/bin/true %s"`, then `unizo_login '{"wait_seconds": 5}'` | `logged_in: false` plus a `login_url` (no-browser path) |
| M6 | `export UNIZO_OIDC_CLIENT_ID=wrong`, then `unizo_login` | The browser shows `Unknown client_id`; the tool returns `login_url` after the wait |
| M7 | `export UNIZO_OIDC_TOKEN_TYPE=jwt`, then `unizo_status` | `config_problems` lists the bad value; the server still runs |
| M8 | Unset `UNIZO_OIDC_*` and set `UNIZO_API_TOKEN=x`, then `unizo_status` | `auth_mode: static-token`; the fake gateway answers 401 with a token hint |

**Don't open a browser** (CI, remote shells): `export BROWSER="/path/to/script %s"`, where the script runs
`curl -s -L -o /dev/null "$1"`. That's enough for the fake IdP. Don't use `/usr/bin/false` for this: Python then
falls back to your default browser.

**Optional: MCP Inspector**, a GUI for listing and calling tools (needs Node.js):

```bash
npx @modelcontextprotocol/inspector uv run --project mcp-server unizo-mcp
```

The server inherits the `UNIZO_*` variables exported in that shell.

### 5.4 Interactive test in Claude Code

1. **Start the fake deployment** ([5.2](#52-the-fake-deployment)).
2. **Install from your checkout:**

   ```bash
   claude plugin marketplace add "$PWD"
   claude plugin install unizo@unizo
   ```

3. **Point it at the fake deployment:**

   ```bash
   export UNIZO_API_URL=http://127.0.0.1:9401 UNIZO_OIDC_ISSUER=http://127.0.0.1:9400 \
          UNIZO_OIDC_CLIENT_ID=unizo-plugin-test
   ```

   Start Claude Code from this same shell in step 5.

4. **Check the servers:** `claude mcp list | grep plugin:unizo` should show `plugin:unizo:unizo ... ✔ Connected`.
   No `unizo-cloud` yet: this setup uses environment variables, not an environment. To test the remote server too, run
   `uv run --project mcp-server unizo-mcp env use demo --file <environments.json>` (it then shows as `unizo-cloud ... ! Needs authentication`).
   That makes the `demo` environment replace the options from step 3, so run `... env off` before the steps below,
   or add a local environment (see C10).
5. **Start Claude Code in a different folder** (not this repo, whose project `.mcp.json` would add unresolved
   copies of the servers) and run through:

| # | Type in Claude Code | Expect |
|---|---|---|
| C1 | `/mcp` | `unizo` connected; `unizo-cloud` "Needs authentication" |
| C1b | `/mcp` → `unizo-cloud` → **Authenticate** | Browser opens the `demo.unizo.ai` Keycloak sign-in; after signing in, `unizo-cloud` shows connected and lists its tools |
| C3 | `/unizo:unizo-plugin-configure` | `unizo_status` → `unizo_login` (browser tab: "Logged in to Unizo") → `unizo_status` with `reachable: true` |
| C4 | "Who am I signed in as in Unizo?" | `analyst@example.com` |
| C5 | Run `curl -X POST 127.0.0.1:9400/admin/revoke-all` in a terminal, then ask "Check my Unizo connection" | Claude reports you're signed out and offers to sign in (or does it) |
| C6 | "Sign me out of Unizo" | `unizo_logout`; a follow-up status shows signed out |
| C8 | Paste a CVE finding: "triage this" | The `exposure-triage` agent gives a priority and next step |
| C9 | `export UNIZO_OIDC_TOKEN_TYPE=jwt`, restart Claude Code, `/unizo:unizo-plugin-configure` | Claude lists the config problem |
| C10 | Put a `local` environment (`api_url` `http://127.0.0.1:9401`, `sso_issuer` `http://127.0.0.1:9400`, `sso_client_id` `unizo-plugin-test`, `remote_mcp` for demo) in an environments file, run `/unizo:unizo-plugin-configure <file> local`, then `/unizo:unizo-plugin-configure <file> demo`, restarting each time | `unizo_status` shows `environment` changing; `claude mcp get unizo-cloud` shows the right URL; `/mcp` asks you to sign in to `unizo-cloud` again after each switch |

To test the **no-browser path** interactively, start Claude Code with `BROWSER="/usr/bin/true %s" claude`. Then,
in C3, Claude shows a sign-in link. Open it in your browser within 10 minutes and ask Claude to check again.

### 5.5 Headless smoke test through Claude

`mcp-server/tests/e2e/claude_smoke.sh` runs three prompts through `claude -p` against the **installed and configured**
plugin and prints which tools Claude called, plus its answers. By default it sets `BROWSER` so no real tab opens
(fine for the fake deployment). This uses your Claude account.

```bash
mcp-server/tests/e2e/claude_smoke.sh /tmp/unizo-smoke
```

Expected (abridged):

```
=== 01-setup: /unizo:unizo-plugin-configure
  tool: unizo_status {}
  tool: unizo_login {}
  tool: unizo_status {}
  answer: ... signed in as analyst@example.com ... gateway is responding ...
=== 02-status: Is my Unizo connection healthy? ...
  tool: unizo_status {}
=== 03-relogin: Sign me out of Unizo, then sign me back in.
  tool: unizo_logout {}
  tool: unizo_login {...}
```

Full transcripts (`*.jsonl`) are kept in the output folder. Against a real IdP, run with `FAKE_BROWSER=0` so you
can complete the sign-in in your browser.

To call Claude yourself:

```bash
claude -p "/unizo:unizo-plugin-configure" \
  --allowedTools "mcp__plugin_unizo_unizo__unizo_status,mcp__plugin_unizo_unizo__unizo_login,mcp__plugin_unizo_unizo__unizo_logout" \
  --max-turns 8
```

Without `--allowedTools`, headless runs can't ask for permission, so the tool calls are denied.

### 5.6 Acceptance test against a real deployment

Do this once per customer environment, with a real user account.

- [ ] `curl -sI https://<gateway>/health` from the user's network answers (401 without a token is fine).
- [ ] `curl -s <issuer>/.well-known/openid-configuration` returns JSON with `authorization_endpoint` and
      `token_endpoint`.
- [ ] Configure the plugin with the customer's values ([2.3](#23-scripted-team-rollout-ci-mdm)), then restart Claude Code.
- [ ] `/unizo:unizo-plugin-configure` → the browser shows the **customer's** sign-in page → "Logged in to Unizo" →
      `reachable: true`.
- [ ] `subject` matches the user's email.
- [ ] Leave Claude Code open past the access token's lifetime (often 1 hour), then ask "check my Unizo connection".
      It should still be reachable with no new sign-in (the refresh token works).
- [ ] Revoke the user's session in the IdP admin console, then check again. Claude asks the user to sign in.
- [ ] `/unizo:unizo-plugin-configure <customer environments.json> <customer env>`, restart, then `/mcp` → `unizo-cloud` → Authenticate → connected, with tools listed.
- [ ] Service-account path: set `api_token` and confirm `auth_mode: static-token` and `reachable: true`.

### 5.7 Clean up after testing

```bash
uv run --project mcp-server unizo-mcp env off   # removes unizo-cloud and the active environment
claude plugin uninstall unizo@unizo
claude plugin marketplace remove unizo
rm -f /tmp/unizo-test-tokens.json
# Also remove cached SSO tokens, if you signed in through Claude Code:
rm -rf ~/.config/unizo-mcp
```

---

## 6. Troubleshooting

Start with `/unizo:unizo-plugin-configure`, or ask Claude to run `unizo_status`. Its `detail` and `config_problems` fields usually
name the fix. For lower-level logs, start Claude Code with `claude --debug=mcp`; MCP server startup errors and stderr appear there.

| Symptom | Likely cause | Fix |
|---|---|---|
| `plugin:unizo:unizo` missing from `claude mcp list` | `api_url` not set, or the plugin was loaded with `--plugin-dir` | Pick an environment with `/unizo:unizo-plugin-configure` (or export `UNIZO_API_URL`), restart. Install via a marketplace, not `--plugin-dir`. |
| `unizo` "Failed to connect" | `uv` not on Claude Code's `PATH` | `command -v uv` in a new terminal; fix the `PATH` in your shell profile; restart Claude Code. |
| No `unizo-cloud` in `/mcp` | No environment active, or the environment has no `remote_mcp` | `/unizo:unizo-plugin-configure <environments.json> <name>`, then restart. |
| "Got new credentials, but ... unizo-cloud rejected them on reconnect" | Sign-in worked, but the server refuses the token (`401 invalid_token`), usually its audience | Fix on the server side: see [4.3](#43-remote-mcp-server-remote_mcp-in-an-environment). Re-authenticating won't help. |
| `unizo-cloud` keeps an old client ID | Cached OAuth client registration | `claude mcp logout unizo-cloud`, then Authenticate again. Switching with `/unizo:unizo-plugin-configure <environments.json> <name>` does this when the client ID changes. |
| `unizo-cloud` "Needs authentication" | Not signed in yet | `/mcp` → `unizo-cloud` → Authenticate. |
| `unizo-cloud` Authenticate fails: "client registration" / "Trusted Hosts" / 403 | Keycloak won't let Claude Code register a client | Ask the administrator to allow anonymous client registration, or register a client and set `remote_mcp.client_id` in the environment ([2.7](#27-environments-switching-between-deployments)). |
| "Could not listen on localhost:8765" | Port in use (often another sign-in still pending) | Close the other process, or set `sso_redirect_port` and register the matching redirect URI. |
| Browser shows "redirect_uri mismatch" / "invalid redirect" | Redirect URI not registered exactly | Register `http://localhost:<port>/callback` for the app. |
| Browser shows "invalid_scope" | Scope not supported (e.g. `offline_access` on Google or Cognito) | Set `sso_scopes` per [2.5](#25-identity-provider-examples). |
| "User is not assigned to this app" | IdP assignment missing | Ask your administrator to assign you to the app. |
| Signed in, but "The Unizo API refused the request (HTTP 401)" | Gateway expects a different token or audience | Try `sso_token_type` = `id`, or set `sso_audience` / the API scope. Check what the gateway validates. |
| HTTP 403 after sign-in | Signed in, but your account lacks Unizo permissions | Ask your Unizo administrator. |
| Asked to sign in every hour | No refresh token | Include `offline_access` (where supported) and enable refresh tokens on the IdP app. |
| "Could not reach the SSO provider" / "Could not reach https://..." | Network, VPN or proxy | Check with `curl`; connect the VPN. |
| `unizo_login` returns `login_url` instead of signing in | No browser could be opened (SSH, headless), or you didn't finish within the wait | Open the URL within 10 minutes, then retry the request. |
| Settings changes have no effect | Claude Code wasn't restarted | Restart Claude Code after switching environments or changing `UNIZO_*` variables. |
| Wrong account | Cached tokens for another user | Ask Claude "sign out of Unizo", then sign in again. |
