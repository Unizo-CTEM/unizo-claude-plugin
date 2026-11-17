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

You do this yourself: read files with the Read tool, write the state file with the Write tool, and run only the
`claude mcp` commands named below with the Bash tool. The plugin ships no scripts and pre-approves nothing, so Claude
Code asks the user to approve each `claude mcp` command: before the first one, say in one line that a few approval
prompts follow and that each one registers, removes, or checks the `unizo-cloud` server.

Never ask the user to paste tokens or secrets into the chat.

## The pieces

**State file.** `$XDG_CONFIG_HOME/unizo-mcp/active-environment.json`, or `~/.config/unizo-mcp/active-environment.json`
when `XDG_CONFIG_HOME` is unset. It records the active environment:

```json
{
  "name": "staging",
  "source": "/Users/me/unizo-envs.json",
  "remote": { "type": "http", "url": "https://unizo-staging.acme.com/mcp", "oauth": { "clientId": "unizo-mcp-staging" } },
  "remote_registered": true,
  "activated_at": "2026-11-17T09:30:00+00:00"
}
```

`source` is the environments file's absolute path. `remote` is exactly the JSON passed to `claude mcp add-json`.
`remote_registered: true` means this command added `unizo-cloud`. If the file is missing, or isn't JSON with a string
`name`, no environment is active. If `remote` has a `headersHelper` key, the server was registered by plugin 0.1.x
and can't connect: treat it as **outdated**.

**Environments file.** A JSON object with an `"environments"` object. Check each environment you use and stop with a
clear message (naming the file and the environment) if any rule fails:

- The name uses only letters, digits, `-`, `_` and `.`.
- The value is an object. It must not contain `api_token` or `sso_client_secret`: secrets don't belong in this file.
- Known keys: `description` (a string) and `remote_mcp`. The older keys `api_url`, `sso_issuer`, `sso_client_id`,
  `sso_scopes`, `sso_audience`, `sso_token_type`, `sso_redirect_port`, `use_env_secrets` and `use_plugin_secrets` are
  accepted and ignored. Any other key is an error.
- `remote_mcp` is an object with only `url` (required), `client_id`, `callback_port` and `scopes`. `url` starts with
  `https://` (`http://` only for `localhost` or `127.0.0.1`). `client_id` and `scopes` are strings. `callback_port`
  is a whole number from 1 to 65535.

The server config for an environment is `{"type": "http", "url": <url>}`, plus an `"oauth"` object holding
`clientId`, `callbackPort` and `scopes` for whichever of `client_id`, `callback_port`, `scopes` are set (leave
`"oauth"` out when none are).

**Server commands** (Bash; quote the JSON in single quotes):

- Exists? `claude mcp get unizo-cloud`: it exists at user scope when it exits 0 and the output has `Scope: User`.
- Sign out: `claude mcp logout unizo-cloud`
- Remove: `claude mcp remove --scope user unizo-cloud`
- Add: `claude mcp add-json --scope user unizo-cloud '<server config JSON>'`

If `claude` isn't found, say the Claude Code CLI must be on the `PATH` and stop.

## 0. Where are we?

- `$ARGUMENTS` is `off`: if no environment is active, say so and stop. Otherwise, if `remote_registered` is true and
  `unizo-cloud` exists, sign it out and remove it. Delete the state file (`rm` on that one path, after showing it),
  say which environment was deactivated, tell the user to restart Claude Code, and stop.
- `$ARGUMENTS` names a file (maybe with an environment name): the user wants to pick or switch. Go to step 1.
- Otherwise read the state file:
  - No environment is active: go to step 1.
  - It's outdated: say in one line that it was registered by an older plugin version and `unizo-cloud` can't
    connect, then go to step 1, sub-step 3, with the state's `source` and `name`.
  - An environment is active: go to step 2.

## 1. Environment (first session)

1. Get the environments file:
   - If `$ARGUMENTS` starts with a path, use it. If a second word follows, that's the environment name: skip to
     sub-step 3 with it.
   - Otherwise ask the user for the path in a short message, and end your turn until they reply: *"Which Unizo
     environments file should I use? Send its path (for example ~/Downloads/environments.json), or run
     `/unizo:unizo-plugin-configure <path>`."* Don't guess a path, and don't look for one on disk.
2. Read the file and list its environments (name, `remote_mcp.url` or "(no remote_mcp)", description; mark the active
   one if the state's `source` is this file). Ask the user which one to use with AskUserQuestion: one option per
   environment (name as the label, remote MCP URL and description as the description; up to 4 options, the user can
   type any other name). If the file holds a single environment, still confirm before switching.
3. Switch to `<name>`:
   1. Read and check the file (rules above). The name must be in it and have a `remote_mcp.url`.
   2. Check whether `unizo-cloud` exists. If it does and the state doesn't say `remote_registered: true`, this command
      didn't add it: ask the user before replacing it. Stop if they say no.
   3. If it exists: when the state's `remote` differs from the new server config, sign it out first (Claude Code keeps
      a server's OAuth client and tokens by name, and a cached client wins over a changed client ID). Then remove it.
   4. Add it with the new server config.
   5. Write the state file (create the folder if needed) with the name, the file's absolute path, the server config,
      `remote_registered: true`, and the current UTC time.

   Report the remote MCP URL and the client ID now in effect ("dynamic client registration" if none). Switching signs
   `unizo-cloud` out whenever its URL or client ID changes; that's expected. If a `claude mcp` command fails, show its
   output verbatim and stop. If the file is missing or invalid, or the name is unknown, explain the format with this
   example and offer to create a file where the user chooses, then stop.

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
4. Tell the user, and stop here:

   > Environment **<name>** is set. Restart Claude Code to load it: quit, then run `claude` again (or
   > `claude --continue` to keep this conversation). Then run `/unizo:unizo-plugin-configure` once more to sign in
   > and check the connection.

## 2. Sign in and check (after the restart)

Say one short line first ("Step 2 of 2: signing in to unizo-cloud").

If the active environment isn't the one just picked (the user hasn't restarted yet), ask them to restart Claude Code
and stop. Then look at the tools you have from `unizo-cloud`:

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
