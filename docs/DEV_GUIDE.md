# Unizo plugin: developer test guide

This guide tests the plugin from a clean state on a developer machine: install it from this checkout, sign in to a
hosted environment, and switch between environments. For configuration, administrator setup and troubleshooting, see
[SETUP_AND_TESTING.md](SETUP_AND_TESTING.md).

## How the pieces fit

```
unizo-cloud   →  https://<env>/mcp   (direct, OAuth)   [registered by /unizo:unizo-plugin-configure, runs on its own]
```

- **`unizo-cloud`** is the remote Unizo MCP server, where the Unizo tools are.
  `/unizo:unizo-plugin-configure <environments.json> <name>` adds it to your Claude Code **user** config
  with `claude mcp add-json` (Claude runs it; the plugin ships no scripts). After that, Claude Code
  connects to it directly and signs in with its own OAuth. It stays registered even if the plugin is turned off, until
  `/unizo:unizo-plugin-configure off` or `claude mcp remove unizo-cloud -s user`.
- The plugin has **no local MCP server, no hooks and no scripts**: it's Markdown and JSON only. The configure
  command tells Claude which `claude mcp` commands to run and how to keep the state file.
- A claude.ai connector for the same backend (for example **Unizo DEV52**) is a separate server that has
  nothing to do with the plugin. Turn it off while testing so you know which tools you're calling.

Environments come only from the file you pass (the plugin ships none and reads none by default). This guide uses
`~/unizo-envs.json`, holding `demo` and `dev52`. The active environment is saved in
`~/.config/unizo-mcp/active-environment.json`, together with the path of the file it came from.

## Step 0: Prerequisites

```bash
cd ~/projects/Unizo-CTEM/unizo-claude-plugin
jq empty ~/unizo-envs.json && echo "unizo-envs.json OK"   # any JSON checker works
claude plugin validate .
```

## Step 1: Reset everything

Close Claude Code, then run in a terminal:

```bash
cd ~/projects/Unizo-CTEM/unizo-claude-plugin
claude mcp logout unizo-cloud 2>/dev/null           # sign out of unizo-cloud
claude mcp remove unizo-cloud -s user 2>/dev/null    # remove the registration
claude plugin uninstall unizo@unizo
claude plugin marketplace remove unizo
rm -rf ~/.config/unizo-mcp                           # remaining state (active environment)
```

Turn off any claude.ai Unizo connector (claude.ai → Settings → Connectors).

Check that everything is gone:

```bash
claude plugin list; claude mcp list; ls ~/.config/unizo-mcp 2>&1
```

## Step 2: Install the plugin

```bash
claude plugin marketplace add ~/projects/Unizo-CTEM/unizo-claude-plugin
claude plugin install unizo@unizo
```

To test the GitHub install path instead: `/plugin marketplace add Unizo-CTEM/unizo-claude-plugin`.

## Step 3: Check that the plugin loads

Start `claude`. `/help` lists `/unizo:unizo-plugin-configure` and `/unizo:unizo-queue`. `/mcp` lists no plugin server:
that's expected. Nothing prompts you to set up: the plugin has no hooks, so you start setup yourself.

## Step 4: Pick the first environment (demo)

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json`. It lists `demo` and `dev52` and asks which to use.
2. Pick `demo`. It reports the remote MCP URL and client ID, and asks you to restart.
3. `claude mcp get unizo-cloud` in a terminal shows the demo URL and client ID, with no `headersHelper`.
4. **Restart Claude Code.**

## Step 5: Sign in (`unizo-cloud`)

1. Run `/unizo:unizo-plugin-configure` (no arguments). Claude calls `mcp__unizo-cloud__authenticate`, then opens the
   URL in your default browser with `open` (allow it if asked) and also shows the link.
2. Sign in. The browser lands on `http://localhost:<port>/callback`, and Claude Code completes the sign-in from that
   page with no paste needed. Check that `<port>` is the environment's `callback_port`. Tell Claude you're done.
3. Claude calls `get_my_context` and reports your demo user and tenant.

Doing it by hand also works: `/mcp` → `unizo-cloud` → **Authenticate**. To test the fallback, sign in, close the
callback tab before it loads (or sign in from another machine), and paste the callback address into the chat: Claude
passes it to `mcp__unizo-cloud__complete_authentication`. "Invalid redirect_uri" means the Keycloak client doesn't
allow `http://localhost:<port>/callback`; set `callback_port` in the environments file or register the port.

## Step 6: Switch to dev52

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json dev52`
2. **Restart Claude Code.**
3. Run `/unizo:unizo-plugin-configure` again to sign in (each realm has its own login; switching signs `unizo-cloud`
   out whenever its URL or client ID changes).
4. *"Call unizo-cloud get_my_context"* returns your dev52 context. That confirms the switch worked.

## Step 7: Switch back and turn off

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json demo`, restart, sign in, and confirm `get_my_context` shows demo.
2. `/unizo:unizo-plugin-configure off`, restart. `unizo-cloud` is gone from `/mcp`.

## Step 8: Check the other plugin pieces

- `/unizo:unizo-queue unclaimed` lists the queue. Opening an Investigation doesn't claim it; any write asks first.
- Ask Claude to move a ticket: it declines and offers a comment instead (a skill rule, not enforced by the plugin).
- Paste a CVE or scanner finding and ask *"triage this"*. This should run the `exposure-triage` agent.

## Step 9: Upgrade path from the local-server version

To check what happens for someone upgrading from a version with the local `unizo` server:

1. With an environment active, edit `~/.config/unizo-mcp/active-environment.json` and add
   `"headersHelper": "old-unizo-helper headers"` to its `remote` object.
2. Run `/unizo:unizo-plugin-configure`. Claude says the environment was set up by an older version and registers it
   again. `claude mcp get unizo-cloud` no longer shows a `headersHelper`.

## Useful commands

```bash
# Inspect, remove or register the remote server by hand (what /unizo:unizo-plugin-configure runs)
claude mcp get unizo-cloud
claude mcp remove unizo-cloud -s user
claude mcp add-json --scope user unizo-cloud '{"type":"http","url":"<url>","oauth":{"clientId":"<client_id>"}}'
cat ~/.config/unizo-mcp/active-environment.json      # the active environment
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Claude says the file isn't valid JSON | `jq empty ~/unizo-envs.json`. A missing comma between environments is the usual cause. |
| `unizo-cloud` missing after switching | `claude mcp get unizo-cloud`, then run `/unizo:unizo-plugin-configure ~/unizo-envs.json <name>` again. |
| `SEP-2352: stored OAuth credential has no 'issuer' stamp` | An old `unizo-cloud` token is still stored. It doesn't block anything. If sign-in acts strangely, use `/mcp` → `unizo-cloud` → **Clear authentication** and sign in again. |
| Tools still show the old environment | You didn't restart Claude Code after switching. |
