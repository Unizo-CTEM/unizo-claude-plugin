---
description: Set up the Unizo plugin end to end - pick an environment from your environments.json, register the unizo-cloud MCP server for it, and sign in
argument-hint: "<path-to-environments.json> [<environment name>] | off"
---

Connect this plugin to the user's Unizo deployment (GCP or AWS) in one guided flow:
**environment → sign in → restart → check**. The plugin's Unizo tools all come from the remote `unizo-cloud` MCP
server; this command registers it for the environment the user picks and signs in to it right away with Claude Code's
own OAuth (`claude mcp login`, which opens the browser and stores the tokens). Registering a server needs a Claude
Code restart before it loads, so after the restart `unizo-cloud` connects already signed in; running this command
again (no arguments) just checks the connection. Say where you are as you go ("Step 1 of 2: environment").

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
4. Sign in now, so the user doesn't have to after the restart. Skip this sub-step in a remote or SSH session, or
   when no desktop browser is available (for example `xdg-open` is missing or `$DISPLAY` is unset on Linux): go to
   sub-step 5 with "not signed in".
   - Tell the user in one line: "A browser tab will open at your sign-in page. Sign in there and come back; I'll
     wait (up to 5 minutes)."
   - Run `env login` with a Bash timeout of 330000 ms. It runs `claude mcp login unizo-cloud`, which opens the
     browser, receives the callback on `http://localhost:<port>/callback` and stores the tokens. If its output
     includes the sign-in URL, show it too in case the browser didn't open.
   - Exit code 0: signed in. Anything else (failure or timeout): show the output verbatim; the user signs in after
     the restart instead (step 2). If the output mentions "Invalid redirect_uri" or "redirect_uri mismatch", explain
     it as in step 2.
5. Tell the user, and stop here. Signed in:

   > Environment **<name>** is set and you're signed in. Restart Claude Code to load it: quit, then run `claude`
   > again (or `claude --continue` to keep this conversation). `unizo-cloud` connects on its own; run
   > `/unizo:unizo-plugin-configure` once more if you want to check the connection.

   Not signed in:

   > Environment **<name>** is set. Restart Claude Code to load it: quit, then run `claude` again (or
   > `claude --continue` to keep this conversation). Then run `/unizo:unizo-plugin-configure` once more to sign in
   > and check the connection.

## 2. Sign in and check (after the restart)

Say one short line first ("Step 2 of 2: checking the unizo-cloud connection"). Usually step 1 already signed in
and the Unizo tools are there; the sign-in below is the fallback.

If the environment `env current` reports isn't the one just picked (the user hasn't restarted yet), ask them to
restart Claude Code and stop. Then look at the tools you have from `unizo-cloud`:

- **Unizo tools are available** (for example `mcp__unizo-cloud__get_my_context`): call `get_my_context` and go to
  step 3.
- **Only `mcp__unizo-cloud__authenticate`** (and `complete_authentication`): it needs a sign-in.
  1. Call `mcp__unizo-cloud__authenticate`. It returns the sign-in URL and starts Claude Code's listener on
     `http://localhost:<port>/callback`. It does not open a browser.
  2. Open that URL in the user's default browser with one Bash call, quoting the URL exactly as returned:
     `open "<url>"` on macOS, `xdg-open "<url>"` on Linux, `cmd.exe /c start "" "<url>"` on Windows. Skip this
     step in a remote or SSH session, or when no desktop browser is available (for example `xdg-open` is missing
     or `$DISPLAY` is unset on Linux).
  3. Always show the URL too: "A browser tab should open at your sign-in page. If it doesn't, open this link."
     Tell the user that after they sign in the browser returns to a `http://localhost:<port>/callback` page, and
     that Claude Code finishes the sign-in by itself when that page loads.
  4. Wait for the user to say they're done; don't poll. Then call `get_my_context`. If the `unizo-cloud` tools
     still aren't there, the callback didn't reach Claude Code (typical on a remote machine): ask for the full
     address from the browser's address bar and pass it to `mcp__unizo-cloud__complete_authentication`.

  If the browser shows "Invalid redirect_uri" or "redirect_uri mismatch", the OAuth client doesn't allow this
  callback port: say so, and point the user to `remote_mcp.callback_port` in the environments file and their
  administrator (the client must allow `http://localhost:<port>/callback`). The user can also sign in from
  `/mcp` → `unizo-cloud` → **Authenticate**, which opens the browser itself. Don't call `authenticate` in a loop:
  each call starts a new flow and the previous link stops working.
- **No `unizo-cloud` tools at all**: the server isn't loaded. Ask the user to open `/mcp` → `unizo-cloud` →
  Reconnect (or restart Claude Code if it isn't listed), then run this command again. Stop.

If `get_my_context` fails, show the error verbatim and suggest checking the MCP URL and network access (VPN,
firewall, allow-listing). Stop.

## 3. Finish

Tell the user setup is complete, who they're signed in as and which tenant (from `get_my_context`), and that they can
switch environments later with `/unizo:unizo-plugin-configure <path> [<name>]` or remove the connection with
`/unizo:unizo-plugin-configure off`. Then go back to what the user asked in their message, if anything. Suggest
`/unizo:unizo-queue` as a first thing to try.
