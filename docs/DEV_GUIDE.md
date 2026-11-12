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
  by running `scripts/unizo_env.py`, which calls `claude mcp add-json`. After that, Claude Code
  connects to it directly and signs in with its own OAuth. It stays registered even if the plugin is turned off, until
  `/unizo:unizo-plugin-configure off` or `claude mcp remove unizo-cloud -s user`.
- The plugin has **no local MCP server and no hooks**. Its only code is `scripts/unizo_env.py`, standard-library
  Python run with `python3` when the configure command runs it.
- A claude.ai connector for the same backend (for example **Unizo DEV52**) is a separate server that has
  nothing to do with the plugin. Turn it off while testing so you know which tools you're calling.

Environments come only from the file you pass (the plugin ships none and reads none by default). This guide uses
`~/unizo-envs.json`, holding `demo` and `dev52`. The active environment is saved in
`~/.config/unizo-mcp/active-environment.json`, together with the path of the file it came from.

## Step 0: Prerequisites

```bash
python3 --version       # 3.8 or later
cd ~/projects/Unizo-CTEM/unizo-claude-plugin
python3 -m json.tool ~/unizo-envs.json >/dev/null && echo "unizo-envs.json OK"
python3 -m pytest tests -q                 # environment-script tests (needs pytest)
claude plugin validate .
```

## Step 1: Reset everything

Close Claude Code, then run in a terminal:

```bash
cd ~/projects/Unizo-CTEM/unizo-claude-plugin
python3 scripts/unizo_env.py off                     # removes unizo-cloud and the active environment
claude mcp remove unizo-cloud -s user 2>/dev/null    # in case it's still there
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
2. `python3 scripts/unizo_env.py current` prints `OUTDATED`.
3. Run `/unizo:unizo-plugin-configure`. Claude says the environment was set up by an older version and registers it
   again. `claude mcp get unizo-cloud` no longer shows a `headersHelper`.

## Useful commands

```bash
# Environment switcher from a terminal (what /unizo:unizo-plugin-configure runs)
python3 scripts/unizo_env.py [list --file <path> | current | use <name> --file <path> [--force] | off]

# Inspect or recreate the remote server registration
claude mcp get unizo-cloud
claude mcp remove unizo-cloud -s user && python3 scripts/unizo_env.py use <name> --file ~/unizo-envs.json --force
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `env` says `not valid JSON` | `python3 -m json.tool ~/unizo-envs.json`. A missing comma between environments is the usual cause. |
| `unizo-cloud` missing after `use` | `claude mcp get unizo-cloud`, then rerun `use <name>`. Use `--force` only if you added `unizo-cloud` by hand. |
| `SEP-2352: stored OAuth credential has no 'issuer' stamp` | An old `unizo-cloud` token is still stored. It doesn't block anything. If sign-in acts strangely, use `/mcp` → `unizo-cloud` → **Clear authentication** and sign in again. |
| Tools still show the old environment | You didn't restart Claude Code after `use`. |
