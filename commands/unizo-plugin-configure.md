---
description: Set up the Unizo plugin end to end - pick an environment from your environments.json, register the unizo-cloud MCP server for it, and sign in
argument-hint: "<path-to-environments.json> [<environment name>] | off"
---

Connect this plugin to the user's Unizo deployment (GCP or AWS) in one guided flow:
**environment → restart → sign in → check**. The plugin's Unizo tools all come from the remote `unizo-cloud` MCP
server; this command registers it for the environment the user picks, and the user signs in to it with Claude Code's
own OAuth. Registering a server needs a Claude Code restart before it loads, so setup spans two sessions: the user
runs this command once to pick the environment, restarts, and runs it again (no arguments) to sign in. Say where you
are as you go ("Step 1 of 2: environment").

Arguments: `$ARGUMENTS`: the path to the user's environments file, optionally followed by the name of the environment
to switch to; or `off`. There is no default environments file: never fall back to one, always use the file the user
names.

Below, `env` is short for `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/unizo_env.py`, run with the Bash tool. It needs only
`python3` and the `claude` CLI. The plugin pre-approves nothing, so Claude Code asks the user to approve each run: before
the first one, say in one line that a few approval prompts follow and that each runs the plugin's environment script.

Never ask the user to paste tokens or secrets into the chat.

## 0. Where are we?

- `$ARGUMENTS` is `off`: run `env off`, show its output, tell the user to restart Claude Code, and stop.
- `$ARGUMENTS` names a file (maybe with an environment name): the user wants to pick or switch. Go to step 1.
- Otherwise run `env current`:
  - No environment is active: go to step 1.
  - It prints `OUTDATED`: the environment was registered by an older plugin version and `unizo-cloud` can't connect.
    Say so in one line, then go to step 1, sub-step 3, with the file and name `env current` printed.
  - An environment is active: go to step 2.

## 1. Environment (first session)

1. Get the environments file:
   - If `$ARGUMENTS` starts with a path, use it. If a second word follows, that's the environment name: skip to
     sub-step 3 with it.
   - Otherwise ask the user for the path in a short message, and end your turn until they reply: *"Which Unizo
     environments file should I use? Send its path (for example ~/Downloads/environments.json), or run
     `/unizo:unizo-plugin-configure <path>`."* Don't guess a path, and don't look for one on disk.
2. List the environments with `env list --file <path>`. Ask the user which one to use with AskUserQuestion: one
   option per environment (name as the label, remote MCP URL and description as the description; up to 4 options,
   the user can type any other name). If the file holds a single environment, still confirm before switching.
3. Switch with `env use <name> --file <path>`. This registers the remote server `unizo-cloud` at user scope.
   Report the remote MCP URL and client ID now in effect. Switching signs `unizo-cloud` out whenever its URL or
   client ID changes; that's expected. On an error, show it verbatim and:
   - The file is missing or invalid, or the name is unknown: explain the file format with this example and offer to
     create a file where the user chooses, then stop.

     ```json
     {
       "environments": {
         "staging": {
           "description": "Acme staging",
           "remote_mcp": { "url": "https://unizo-staging.acme.com/mcp", "client_id": "unizo-mcp-staging" }
         }
       }
     }
     ```

     `client_id` is optional (leave it out for dynamic client registration); `callback_port` and `scopes` are also
     optional. Never put tokens or client secrets in an environments file.
   - `unizo-cloud` already exists and this command didn't add it: ask the user before re-running with `--force`.
   - Anything else: stop.
4. Tell the user, and stop here:

   > Environment **<name>** is set. Restart Claude Code to load it: quit, then run `claude` again (or
   > `claude --continue` to keep this conversation). Then run `/unizo:unizo-plugin-configure` once more to sign in
   > and check the connection.

## 2. Sign in and check (after the restart)

Say one short line first ("Step 2 of 2: signing in to unizo-cloud").

If the environment `env current` reports isn't the one just picked (the user hasn't restarted yet), ask them to
restart Claude Code and stop. Then look at the tools you have from `unizo-cloud`:

- **Unizo tools are available** (for example `mcp__unizo-cloud__get_my_context`): call `get_my_context` and go to
  step 3.
- **Only `mcp__unizo-cloud__authenticate`** (and `complete_authentication`): it needs a sign-in. Call
  `mcp__unizo-cloud__authenticate` and show the URL it returns ("your browser should open; if not, use this link").
  If the browser can't reach the local callback, pass the URL the user landed on to
  `mcp__unizo-cloud__complete_authentication`. Alternatively the user can open `/mcp` → `unizo-cloud` →
  **Authenticate**. When they say they're done, call `get_my_context`. Don't call `authenticate` in a loop.
- **No `unizo-cloud` tools at all**: the server isn't loaded. Ask the user to open `/mcp` → `unizo-cloud` →
  Reconnect (or restart Claude Code if it isn't listed), then run this command again. Stop.

If `get_my_context` fails, show the error verbatim and suggest checking the MCP URL and network access (VPN,
firewall, allow-listing). Stop.

## 3. Finish

Tell the user setup is complete, who they're signed in as and which tenant (from `get_my_context`), and that they can
switch environments later with `/unizo:unizo-plugin-configure <path> [<name>]` or remove the connection with
`/unizo:unizo-plugin-configure off`. Then go back to what the user asked in their message, if anything. Suggest
`/unizo:unizo-queue` as a first thing to try.
