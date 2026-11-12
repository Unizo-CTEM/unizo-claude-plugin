# Unizo plugin: setup and testing guide

This guide covers installing the Unizo plugin for Claude Code, connecting it to your organization's Unizo
deployment (GCP or AWS), and testing it.

| If you are... | Read |
|---|---|
| A user connecting to your company's deployment | [1. Install](#1-install), [2. Configure](#2-configure), [3. Verify](#3-verify-the-setup) |
| An administrator preparing a deployment | [4. Administrator setup](#4-administrator-setup) |
| A developer or QA engineer testing the plugin | [5. Testing](#5-testing) |
| Stuck | [6. Troubleshooting](#6-troubleshooting) |

---

## How the plugin connects

```
Claude Code
 └── unizo-cloud  (remote MCP server, HTTP + OAuth)  ──►  remote_mcp.url of the active environment

 <your environments.json>  ──►  /unizo:unizo-plugin-configure <environments.json> [<name>]
                                 registers unizo-cloud for the environment you pick
```

- **`unizo-cloud`** is the remote Unizo MCP server, where every Unizo tool lives. The configure command registers it
  in your Claude Code user config, and Claude Code signs you in to it with its own OAuth. Calls go straight from
  Claude Code to the server.
- The plugin ships **no MCP server of its own** and installs nothing: its hooks and its environment script
  (`scripts/unizo_env.py`) are standard-library Python run with `python3`.
- **Environments** ([2.2](#22-environments-switching-between-deployments)) name the remote server URL and OAuth client ID
  per deployment, so you can switch with one command.
- **Commands:** `/unizo:unizo-plugin-configure` (pick or switch an environment, sign in, check the connection) and
  `/unizo:unizo-queue` (work your review queue). **Skill:** `unizo-review-queue`. **Agent:** `exposure-triage`.
  **Hooks:** `unizo_onboard` (setup prompts at session start) and `unizo_guard` (asks before writes, blocks ticket
  moves, requires a preview before a commit, audits writes).

---

## 1. Install

### Prerequisites

| Requirement | Check |
|---|---|
| Claude Code | `claude --version` |
| `python3` 3.8 or later, on the `PATH` Claude Code sees | `python3 --version` |
| HTTPS access to your Unizo MCP server | `curl -sI https://<your-unizo>/mcp` (a `401` is fine) |

### Install from the marketplace

In Claude Code:

```
/plugin marketplace add Unizo-CTEM/unizo-claude-plugin
/plugin install unizo@unizo
```

Or from a terminal:

```
claude plugin marketplace add Unizo-CTEM/unizo-claude-plugin
claude plugin install unizo@unizo
```

### Install from a local folder (development, QA, air-gapped)

```
claude plugin marketplace add /path/to/unizo-claude-plugin
claude plugin install unizo@unizo
```

---

## 2. Configure

### 2.1 Guided setup

1. Get an environments file from your administrator ([4.2](#42-values-to-send-your-users)).
2. Restart Claude Code, then run `/unizo:unizo-plugin-configure <path-to-environments.json>`. Claude also offers this in
   its first reply until the plugin is set up.
3. Pick an environment. The command registers `unizo-cloud` for it and asks you to restart.
4. Restart Claude Code (`claude`, or `claude --continue` to keep the conversation). Your first message finishes setup:
   Claude signs you in to `unizo-cloud` (a browser tab opens at your company's sign-in page) and checks the
   connection with `get_my_context`.

You can also sign in yourself: `/mcp` → `unizo-cloud` → **Authenticate**.

### 2.2 Environments: switching between deployments

```
/unizo:unizo-plugin-configure ~/acme-envs.json           # pick from the file, then restart
/unizo:unizo-plugin-configure ~/acme-envs.json staging   # switch straight to staging, then restart
/unizo:unizo-plugin-configure off                        # remove unizo-cloud, then restart
```

From a terminal: `python3 <plugin-dir>/scripts/unizo_env.py [list --file <path> | current | use <name> --file <path> [--force] | off]`.

The file format:

```json
{
  "environments": {
    "demo": {
      "description": "Unizo demo",
      "remote_mcp": { "url": "https://demo.unizo.ai/mcp", "client_id": "dW5pem8tbWNwLWNsaWVudA==" }
    },
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
| `remote_mcp.callback_port` | Pins the local OAuth callback port; otherwise Claude Code picks one |
| `remote_mcp.scopes` | OAuth scopes to request, if the server needs specific ones |
| `description` | Shown in the list |

Keys from earlier plugin versions (`api_url`, `sso_*`, `use_env_secrets`) are accepted and ignored. Secrets
(`api_token`, `sso_client_secret`) are refused.

How switching works:
- `use` registers `unizo-cloud` at user scope with `claude mcp add-json`. The plugin can't ship it in a `.mcp.json`:
  Claude Code reads a remote server's `oauth.clientId` literally and doesn't substitute `${ENV_VAR}` there.
- When the URL or client ID changes, `use` signs the old server out (`claude mcp logout unizo-cloud`), because Claude
  Code would otherwise reuse the cached OAuth client. You sign in again after the restart.
- `use` won't replace a `unizo-cloud` server it didn't add unless you pass `--force`; the configure command asks first.
- The active environment is recorded in `~/.config/unizo-mcp/active-environment.json` (or under
  `$XDG_CONFIG_HOME`), with the file it came from. The onboarding hook reads it.

### 2.3 Upgrading from a version with the local `unizo` server

Earlier versions shipped a local `unizo` MCP server, run with `uv`, that signed in to the Unizo gateway and passed its
token to `unizo-cloud` through a `headersHelper`. That server is gone. If your environment was set up by an earlier
version, the onboarding hook says so at the next session start. Run
`/unizo:unizo-plugin-configure <environments.json> <name>` again, restart, and sign in once through `/mcp`.
`~/.config/unizo-mcp/tokens.json` (the old gateway token cache) is no longer used and can be deleted.

---

## 3. Verify the setup

1. `claude mcp get unizo-cloud` shows `Scope: User config`, the environment's URL, and its OAuth client ID.
2. In Claude Code, `/mcp` shows `unizo-cloud` as connected (or **Needs authentication** before you sign in).
3. Ask Claude: *"Call unizo-cloud get_my_context"*. It returns your user and tenant.
4. `python3 <plugin-dir>/scripts/unizo_env.py current` shows the environment and `setup complete: True`.

---

## 4. Administrator setup

### 4.1 Remote MCP server (`remote_mcp` in an environment)

- [ ] Reachable over HTTPS from users' machines (VPN, allow-listing, etc.).
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
- [ ] Users are assigned to the client or realm, with the Unizo permissions they need.

### 4.2 Values to send your users

Send an environments file. Users save it anywhere (or use a shared copy) and pass its path to the configure command:

```json
{
  "environments": {
    "acme": {
      "description": "Acme production",
      "remote_mcp": { "url": "https://unizo.acme.com/mcp", "client_id": "unizo-mcp-acme" }
    }
  }
}
```

Then they run `/unizo:unizo-plugin-configure <path-to-the-file> acme`, restart Claude Code, and sign in.

---

## 5. Testing

All commands run from the repository root.

### 5.1 Automated tests

```bash
python3 -m pytest tests -q        # needs pytest
```

They cover the guard hook (writes ask, ticket moves denied, commit needs a matching recent preview, re-draft and
reject invalidate previews, audit log), the onboarding hook (fresh install, unfinished setup, registrations from older
versions, corrupt state), and `scripts/unizo_env.py` (file parsing, registering and replacing `unizo-cloud` with a fake
`claude` CLI, sign-out on a client change, `off`, `setup-done`, the CLI). No network or Claude account is needed.

Also run `claude plugin validate .`.

### 5.2 Interactive test in Claude Code

1. Install from your checkout: `claude plugin marketplace add "$PWD"`, then `claude plugin install unizo@unizo`.
2. Start Claude Code **in a different folder** and run through:

| # | Do | Expect |
|---|---|---|
| C1 | First message in a new session | Claude offers `/unizo:unizo-plugin-configure` |
| C2 | `/unizo:unizo-plugin-configure <file>` | Lists the environments, asks which one, registers `unizo-cloud`, asks you to restart |
| C3 | Restart, send any message | Claude finishes setup on its own: signs in to `unizo-cloud` (browser opens), calls `get_my_context`, records setup as done |
| C4 | Restart again, send any message | No setup prompt |
| C5 | `/unizo:unizo-plugin-configure <file> <other env>`, restart | `claude mcp get unizo-cloud` shows the new URL; Claude asks you to sign in again |
| C6 | `/unizo:unizo-queue unclaimed` | Queue table; opening an Investigation needs no claim; writes ask first |
| C7 | Ask Claude to move a ticket or set a Jira assignee | The guard hook blocks it |
| C8 | Paste a CVE finding: "triage this" | The `exposure-triage` agent gives a priority and next step |
| C9 | `/unizo:unizo-plugin-configure off`, restart | `unizo-cloud` is gone from `/mcp`; the setup prompt is back |

### 5.3 Acceptance test against a real deployment

Do this once per customer environment, with a real user account.

- [ ] `curl -sI <remote_mcp.url>` from the user's network answers (`401` without a token is expected).
- [ ] `/unizo:unizo-plugin-configure <customer environments.json> <customer env>`, restart, and sign in: the browser
      shows the **customer's** sign-in page and `unizo-cloud` connects with its tools listed.
- [ ] `get_my_context` returns the user's own account and the right tenant.
- [ ] Leave Claude Code open past the access token's lifetime, then call `get_my_context` again. It still works
      with no new sign-in (the refresh token works).

### 5.4 Clean up after testing

```bash
python3 scripts/unizo_env.py off       # removes unizo-cloud and the active environment
claude plugin uninstall unizo@unizo
claude plugin marketplace remove unizo
rm -rf ~/.config/unizo-mcp             # remaining state: hook state and the audit log
```

---

## 6. Troubleshooting

For lower-level logs, start Claude Code with `claude --debug=mcp`.

| Symptom | Likely cause | Fix |
|---|---|---|
| No `unizo-cloud` in `/mcp` | No environment active, or Claude Code wasn't restarted | `/unizo:unizo-plugin-configure <environments.json> <name>`, then restart. |
| `unizo-cloud` fails right after upgrading the plugin | It was registered by an older version, whose `headersHelper` ran the removed local server | `/unizo:unizo-plugin-configure <environments.json> <name>` again, restart, sign in. The onboarding hook points this out. |
| `unizo-cloud` "Needs authentication" | Not signed in yet | `/mcp` → `unizo-cloud` → Authenticate, or let `/unizo:unizo-plugin-configure` do it. |
| "Got new credentials, but ... unizo-cloud rejected them on reconnect" | Sign-in worked, but the server refuses the token (`401 invalid_token`), usually its audience | Fix on the server side: see [4.1](#41-remote-mcp-server-remote_mcp-in-an-environment). Re-authenticating won't help. |
| `unizo-cloud` keeps an old client ID | Cached OAuth client registration | `claude mcp logout unizo-cloud`, then Authenticate again. Switching environments does this when the client ID changes. |
| Authenticate fails: "client registration" / "Trusted Hosts" / 403 | Keycloak won't let Claude Code register a client | Ask the administrator to allow anonymous client registration, or register a client and set `remote_mcp.client_id`. |
| Browser shows "redirect_uri mismatch" | Redirect URI not registered for the client | Register `http://localhost:<port>/callback`, and pin the port with `remote_mcp.callback_port`. |
| `use` says `unizo-cloud` "already exists and wasn't added by this command" | You added a `unizo-cloud` server by hand | Remove it (`claude mcp remove --scope user unizo-cloud`) or let the configure command re-run with `--force`. |
| `env` says `not valid JSON` | Syntax error in the environments file | `python3 -m json.tool <file>`. A missing comma between environments is the usual cause. |
| The setup prompt appears every session | Setup never reached `setup-done` | Run `/unizo:unizo-plugin-configure` and finish the sign-in. |
| HTTP 403 from Unizo tools | Signed in, but your account lacks Unizo permissions | Ask your Unizo administrator. |
| Tools still show the old environment | Claude Code wasn't restarted after switching | Restart Claude Code. |
