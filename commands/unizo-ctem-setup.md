---
description: Set up the CTEM plugin end to end - pick an environment from your environments.json, and sign in once (SSO) for both the gateway and the unizo-ctem-cloud MCP server
argument-hint: "[<path-to-environments.json>]"
allowed-tools: Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env:*), Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp login)
---

Connect this plugin to the user's Unizo CTEM deployment (GCP or AWS) in one guided flow:
**environment → sign in → restart → check**. The user signs in **once**: the gateway's SSO token is also what the
remote `unizo-ctem-cloud` server sends (its `headersHelper` runs `unizo-ctem-mcp headers`), so there is no second
sign-in for the MCP server. Picking an environment needs a Claude Code restart before the servers use it, so setup
spans two sessions; after the restart, the session-start hook has Claude run this command again automatically on the
user's first message, and it only checks that everything is connected. Say where you are as you go
("Step 1 of 2: environment and sign-in").

Arguments: `$ARGUMENTS` (optional path to an environments file)

Never ask the user to paste tokens or secrets into the chat; secrets belong in environment variables.

## 0. Check the local server

Call `unizo_ctem_status`. If the `unizo-ctem` MCP server is not available at all, tell the user to check `/mcp` (the
server needs `uv` on the `PATH`) and restart Claude Code, then stop.

Do step 1 if **any** of these is true; otherwise go to step 2:

- `$ARGUMENTS` names an environments file (the user wants to pick or switch environments), or
- `environment` is not set **and** `api_url` is empty (nothing configured yet).

If `environment` is not set but `api_url` is configured, the user set `UNIZO_CTEM_*` environment variables and doesn't
need an environment: go to step 2 (there is no remote server).

## 1. Environment and sign-in (first session)

1. Get the environments file:
   - If `$ARGUMENTS` is a path, use it.
   - Otherwise ask with AskUserQuestion: *"Where is your CTEM environments.json file? Choose Other to type its
     path (for example ~/Downloads/environments.json)."* Options: **Bundled environments** ("The demo
     environments shipped with the plugin") and **My config file** ("~/.config/unizo-ctem-mcp/environments.json").
     A typed path is the answer most users give.
2. Invoke the `unizo-ctem:unizo-ctem-env` skill with the Skill tool: pass the path as its argument, or no
   argument for **Bundled environments** / **My config file** (it reads both by default). It lists the
   environments, asks the user which one to use, and switches to it, which also registers the remote server
   `unizo-ctem-cloud`. If it fails, show its error and stop.
3. Sign in now, before the restart, so both servers connect when Claude Code starts again. Run
   `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp login` with the Bash tool and
   `run_in_background: true` (it reads the environment just picked, opens the browser and waits up to 10 minutes).
   Read its output file once to get the sign-in URL, show it ("your browser should open; if not, use this link"),
   and wait for the command to finish. Don't start it twice.
   - `SSO is not configured`: the environment uses an API token or has no auth; skip the sign-in.
   - Timed out or an SSO error: show the error. The user can still restart; the sign-in then happens in step 2.
4. Tell the user, and stop here:

   > Environment **<name>** is set and you're signed in as **<user>**. Restart Claude Code to load it: quit, then run
   > `claude` again (or `claude --continue` to keep this conversation). Your first message after the restart
   > finishes setup; you won't need to sign in again.

## 2. Check the connection (after the restart)

When this runs automatically after a restart, don't ask whether to start: say one short line first
("Finishing CTEM setup: checking your connection").

If `environment` from step 0 doesn't match the environment just picked (the user hasn't restarted yet), ask them to
restart Claude Code and stop.

Summarize the status in a few lines: environment and the file it came from, API URL, auth mode (`static-token`,
`sso`, or `none`), who is signed in, and whether the gateway is reachable. List any `config_problems` verbatim.
Then:

- `auth_mode` is `none`: they need either an API token or SSO settings (issuer URL + client ID, from their identity
  provider admin), in the environments file (secrets as `UNIZO_CTEM_API_TOKEN` / `UNIZO_CTEM_OIDC_CLIENT_SECRET`
  environment variables with `"use_env_secrets": true`). Changes apply after a restart. Stop.
- `auth_mode` is `sso` and not signed in (the step 1 sign-in was skipped or failed, or the token expired and can't
  refresh): call `unizo_ctem_login` once. If it returns a `login_url`, show it, ask the user to finish signing in
  there, and call `unizo_ctem_status` again when they say they're done. Don't call `unizo_ctem_login` in a loop.
  The remote server connected at startup without a token, so it needs a reconnect (not another sign-in): ask the
  user to open `/mcp` → `unizo-ctem-cloud` → **Reconnect**.
- Gateway not reachable after sign-in: show the `detail` and suggest checking the API URL and network access (VPN,
  firewall, allow-listing). Stop.

## 3. Remote MCP server (`unizo-ctem-cloud`)

Skip this step if no environment is active (environment variables only): there's no remote server.

Run `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env current`. If its `remote_mcp` is
`null`, the environment has no remote server: go to step 4. Otherwise look at the tools you have from
`unizo-ctem-cloud`:

- **Other `mcp__unizo-ctem-cloud__*` tools are available**: it's connected with the gateway sign-in. Nothing to do.
- **Only `mcp__unizo-ctem-cloud__authenticate`** (and `complete_authentication`): the server didn't accept or didn't
  get the gateway token. If you just signed in in step 2, the reconnect above fixes it. Otherwise, possible causes:
  this folder isn't trusted yet (Claude Code skips `headersHelper` in untrusted folders; trust it and restart), or
  `remote_mcp` in the environment didn't record a `headersHelper` (switch again with `/unizo-ctem:unizo-ctem-env use
  <name>` and restart). As a last resort, call `mcp__unizo-ctem-cloud__authenticate` and show the URL it returns;
  the SSO session from the gateway sign-in usually means one click, no password. If the browser can't reach the
  local callback, pass the URL they landed on to `mcp__unizo-ctem-cloud__complete_authentication`.
- **No `unizo-ctem-cloud` tools at all**: the server isn't loaded. Ask the user to open `/mcp` → `unizo-ctem-cloud`
  → Reconnect (or restart Claude Code if it isn't listed), then run this command again. Stop.

## 4. Finish

When the gateway is reachable and the remote server is connected (or there is none), record it so the
session-start hook stops:

```
uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env setup-done
```

(Skip this when no environment is active.) Then tell the user setup is complete, who they're signed in as, and that
they can switch environments later with `/unizo-ctem:unizo-ctem-setup <path>` or `/unizo-ctem:unizo-ctem-env use <name>`.
Then go back to what the user asked in their message, if anything. Suggest `/unizo-ctem:unizo-ctem-queue` as a
first thing to try.
