---
description: Set up the CTEM plugin end to end - pick an environment from your environments.json, sign in to the gateway (SSO) and to the unizo-ctem-cloud MCP server
argument-hint: "[<path-to-environments.json>]"
allowed-tools: Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env:*)
---

Connect this plugin to the user's Unizo CTEM deployment (GCP or AWS) in one guided flow:
**environment → restart → gateway sign-in → remote MCP sign-in**. Picking an environment needs a Claude Code restart
before the servers use it, so setup runs in two sessions; the session-start hook reminds the user to run this
command again after the restart. Say where you are in the flow as you go ("Step 1 of 3: environment").

Arguments: `$ARGUMENTS` (optional path to an environments file)

## 0. Check the local server

Call `unizo_ctem_status`. If the `unizo-ctem` MCP server is not available at all, tell the user to check `/mcp` (the
server needs `uv` on the `PATH`) and restart Claude Code, then stop.

## 1. Environment

Do this step if **any** of these is true; otherwise go to step 2:

- `$ARGUMENTS` names an environments file (the user wants to pick or switch environments), or
- `environment` is not set **and** `api_url` is empty (nothing configured yet).

If `environment` is not set but `api_url` is configured, the user set up the plugin options with `/plugin configure`
and doesn't need an environment: skip to step 2 (there will be no remote server; mention that in step 3).

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
3. Once the switch succeeded, tell the user, and stop here:

   > Environment **<name>** is set. Restart Claude Code to load it: quit, run `claude` again (or `claude --continue`
   > to keep this conversation), then run **/unizo-ctem:unizo-ctem-setup** again to sign in. You'll see a reminder
   > when Claude Code starts.

## 2. Gateway sign-in (SSO)

If `environment` from step 0 doesn't match the environment just picked (the user hasn't restarted yet), ask them to
restart Claude Code and stop.

Summarize the status in a few lines: environment and the file it came from, API URL, auth mode (`static-token`,
`sso`, or `none`), who is signed in, and whether the gateway is reachable. List any `config_problems` verbatim.
Then:

- `auth_mode` is `none`: they need either an API token or SSO settings (issuer URL + client ID, from their identity
  provider admin), in the environments file or in `/plugin configure unizo-ctem@unizo-ctem`. Changes apply after a
  restart. Stop.
- `auth_mode` is `sso` and not signed in, or the token expired and can't refresh: call `unizo_ctem_login` once. If it
  returns a `login_url`, show it, ask the user to finish signing in there, and call `unizo_ctem_status` again when
  they say they're done. Don't call `unizo_ctem_login` in a loop.
- Gateway not reachable after sign-in: show the `detail` and suggest checking the API URL and network access (VPN,
  firewall, allow-listing). Stop.

## 3. Remote MCP sign-in (`unizo-ctem-cloud`)

Skip this step if no environment is active (plugin options only): there's no remote server.

Run `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env current`. If its `remote_mcp` is
`null`, the environment has no remote server: skip to step 4. Otherwise look at the tools you have from
`unizo-ctem-cloud`:

- **Only `mcp__unizo-ctem-cloud__authenticate`** (and `complete_authentication`): the server isn't signed in. Call
  `mcp__unizo-ctem-cloud__authenticate`. Show the user the sign-in URL it returns and ask them to finish signing in
  in the browser. If the browser can't reach the local callback, they can paste the URL they landed on, and you pass
  it to `mcp__unizo-ctem-cloud__complete_authentication`. When it succeeds, the server's real tools appear.
- **Other `mcp__unizo-ctem-cloud__*` tools are available**: it's already signed in.
- **No `unizo-ctem-cloud` tools at all**: the server isn't loaded. Ask the user to open `/mcp` → `unizo-ctem-cloud`
  → Authenticate (or restart Claude Code if it isn't listed), then run this command again. Stop.

## 4. Finish

When the gateway is reachable and the remote server is signed in (or there is none), record it so the
session-start reminder stops:

```
uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env setup-done
```

(Skip this when no environment is active.) Then tell the user setup is complete, who they're signed in as, and that
they can switch environments later with `/unizo-ctem:unizo-ctem-setup <path>` or `/unizo-ctem:unizo-ctem-env use <name>`.
Suggest `/unizo-ctem:queue` as a first thing to try.

Never ask the user to paste tokens or secrets into the chat; secrets belong in `/plugin configure`.
