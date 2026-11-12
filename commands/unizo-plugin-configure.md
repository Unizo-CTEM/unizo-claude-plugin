---
description: Set up the Unizo plugin end to end - pick an environment from your environments.json, and sign in once (SSO) for both the gateway and the unizo-cloud MCP server
argument-hint: "<path-to-environments.json> [<environment name>]"
allowed-tools: Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp env:*), Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp login)
---

Connect this plugin to the user's Unizo deployment (GCP or AWS) in one guided flow:
**environment → sign in → restart → check**. The user signs in **once**: the gateway's SSO token is also what the
remote `unizo-cloud` server sends (its `headersHelper` runs `unizo-mcp headers`), so there is no second
sign-in for the MCP server. Picking an environment needs a Claude Code restart before the servers use it, so setup
spans two sessions; after the restart, the session-start hook has Claude run this command again automatically on the
user's first message, and it only checks that everything is connected. Say where you are as you go
("Step 1 of 2: environment and sign-in").

Arguments: `$ARGUMENTS`: the path to the user's environments file, optionally followed by the name of the environment
to switch to. There is no default environments file: never fall back to one, always use the file the user names.

Never ask the user to paste tokens or secrets into the chat; secrets belong in environment variables.

## 0. Check the local server

Call `unizo_status`. If the `unizo` MCP server is not available at all, tell the user to check `/mcp` (the
server needs `uv` on the `PATH`) and restart Claude Code, then stop.

Do step 1 if **any** of these is true; otherwise go to step 2:

- `$ARGUMENTS` is set (an environments file, maybe with a name: the user wants to pick or switch), or
- `environment` is not set **and** `api_url` is empty (nothing configured yet).

If `environment` is not set but `api_url` is configured, the user set `UNIZO_*` environment variables and doesn't
need an environment: go to step 2 (there is no remote server).

## 1. Environment and sign-in (first session)

Environments are defined in a JSON file the user names; the plugin ships none and reads none by default. Below,
`env` is short for `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp env`, run with the Bash
tool.

1. Get the environments file:
   - If `$ARGUMENTS` starts with a path, use it. If a second word follows, that's the environment name: skip to
     sub-step 3 with it.
   - Otherwise ask the user for the path in a short message, and end your turn until they reply: *"Which Unizo
     environments file should I use? Send its path (for example ~/Downloads/environments.json), or run
     `/unizo:unizo-plugin-configure <path>`."* Don't guess a path, and don't look for one on disk.
2. List the environments with `env list --file <path>`. Ask the user which one to use with AskUserQuestion: one
   option per environment (name as the label, gateway URL and description as the description; up to 4 options, the
   user can type any other name). If the file holds a single environment, still confirm before switching.
3. Switch with `env use <name> --file <path>`. This also registers the remote server
   `unizo-cloud`. Report the gateway, SSO issuer and remote MCP URL + client ID now in effect. Switching signs
   the remote server out whenever its URL or client ID changes; that's expected. On an error, show it verbatim and:
   - The file is missing or invalid, or the name is unknown: explain the file format with this example and offer to
     create a file where the user chooses, then stop.

     ```json
     {
       "environments": {
         "staging": {
           "description": "Acme staging",
           "api_url": "https://unizo-staging.acme.com",
           "sso_issuer": "https://acme.okta.com/oauth2/default",
           "sso_client_id": "0oa-staging-client",
           "remote_mcp": { "url": "https://unizo-staging.acme.com/mcp", "client_id": "unizo-mcp-staging" }
         }
       }
     }
     ```

     Never put API tokens or client secrets in an environments file. The user exports them as
     `UNIZO_API_TOKEN` / `UNIZO_OIDC_CLIENT_SECRET` before starting Claude Code, and an environment uses
     them only if it sets `"use_env_secrets": true`.
   - `unizo-cloud` already exists and the plugin didn't add it: ask the user before re-running with `--force`.
   - Anything else: stop.
4. Sign in now, before the restart, so both servers connect when Claude Code starts again. Run
   `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp login` with the Bash tool and
   `run_in_background: true` (it reads the environment just picked, opens the browser and waits up to 10 minutes).
   Read its output file once to get the sign-in URL, show it ("your browser should open; if not, use this link"),
   and wait for the command to finish. Don't start it twice.
   - `SSO is not configured`: the environment uses an API token or has no auth; skip the sign-in.
   - Timed out or an SSO error: show the error. The user can still restart; the sign-in then happens in step 2.
5. Tell the user, and stop here:

   > Environment **<name>** is set and you're signed in as **<user>**. Restart Claude Code to load it: quit, then run
   > `claude` again (or `claude --continue` to keep this conversation). Your first message after the restart
   > finishes setup; you won't need to sign in again.

## 2. Check the connection (after the restart)

When this runs automatically after a restart, don't ask whether to start: say one short line first
("Finishing Unizo setup: checking your connection").

If `environment` from step 0 doesn't match the environment just picked (the user hasn't restarted yet), ask them to
restart Claude Code and stop.

Summarize the status in a few lines: environment and the file it came from, API URL, auth mode (`static-token`,
`sso`, or `none`), who is signed in, and whether the gateway is reachable. List any `config_problems` verbatim.
Then:

- `auth_mode` is `none`: they need either an API token or SSO settings (issuer URL + client ID, from their identity
  provider admin), in the environments file (secrets as `UNIZO_API_TOKEN` / `UNIZO_OIDC_CLIENT_SECRET`
  environment variables with `"use_env_secrets": true`). Changes apply after a restart. Stop.
- `auth_mode` is `sso` and not signed in (the step 1 sign-in was skipped or failed, or the token expired and can't
  refresh): call `unizo_login` once. If it returns a `login_url`, show it, ask the user to finish signing in
  there, and call `unizo_status` again when they say they're done. Don't call `unizo_login` in a loop.
  The remote server connected at startup without a token, so it needs a reconnect (not another sign-in): ask the
  user to open `/mcp` → `unizo-cloud` → **Reconnect**.
- Gateway not reachable after sign-in: show the `detail` and suggest checking the API URL and network access (VPN,
  firewall, allow-listing). Stop.

## 3. Remote MCP server (`unizo-cloud`)

Skip this step if no environment is active (environment variables only): there's no remote server.

Run `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp env current`. If its `remote_mcp` is
`null`, the environment has no remote server: go to step 4. Otherwise look at the tools you have from
`unizo-cloud`:

- **Other `mcp__unizo-cloud__*` tools are available**: it's connected with the gateway sign-in. Nothing to do.
- **Only `mcp__unizo-cloud__authenticate`** (and `complete_authentication`): the server didn't accept or didn't
  get the gateway token. If you just signed in in step 2, the reconnect above fixes it. Otherwise, possible causes:
  this folder isn't trusted yet (Claude Code skips `headersHelper` in untrusted folders; trust it and restart), or
  `remote_mcp` in the environment didn't record a `headersHelper` (switch again with `/unizo:unizo-plugin-configure
  <path> <name>` and restart). As a last resort, call `mcp__unizo-cloud__authenticate` and show the URL it returns;
  the SSO session from the gateway sign-in usually means one click, no password. If the browser can't reach the
  local callback, pass the URL they landed on to `mcp__unizo-cloud__complete_authentication`.
- **No `unizo-cloud` tools at all**: the server isn't loaded. Ask the user to open `/mcp` → `unizo-cloud`
  → Reconnect (or restart Claude Code if it isn't listed), then run this command again. Stop.

## 4. Finish

When the gateway is reachable and the remote server is connected (or there is none), record it so the
session-start hook stops:

```
uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-mcp env setup-done
```

(Skip this when no environment is active.) Then tell the user setup is complete, who they're signed in as, and that
they can switch environments later with `/unizo:unizo-plugin-configure <path> [<name>]`.
To turn environments off, run `env off` and restart.
Then go back to what the user asked in their message, if anything. Suggest `/unizo:unizo-queue` as a
first thing to try.
