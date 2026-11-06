# Unizo CTEM plugin: developer test guide

This guide tests the plugin from a clean state on a developer machine: install it from this checkout, sign in to a
hosted environment, and switch between environments. For configuration, administrator setup, and the fake deployment,
see [SETUP_AND_TESTING.md](SETUP_AND_TESTING.md).

## How the pieces fit

```
plugin:unizo-ctem:unizo-ctem   →  local process (uv run unizo-ctem-mcp) →  CTEM gateway API   [part of the plugin]
unizo-ctem-cloud         →  https://<env>/mcp               (direct, OAuth)      [registered by /unizo-ctem:unizo-ctem-setup, runs on its own]
```

- **`plugin:unizo-ctem:unizo-ctem`** is the plugin's local stdio server. It has only `unizo_ctem_status`, `unizo_ctem_login`, and
  `unizo_ctem_logout`, and signs in to the gateway with SSO.
- **`unizo-ctem-cloud`** is the remote CTEM MCP server, where the CTEM tools are. `/unizo-ctem:unizo-ctem-setup <name>` adds it to
  your Claude Code **user** config (`~/.claude.json`). After that, Claude Code connects to it directly. Calls don't
  go through the plugin. It stays registered even if the plugin is turned off, until `unizo-ctem-mcp env off` or
  `claude mcp remove unizo-ctem-cloud -s user`.
- A claude.ai connector for the same backend (for example **Unizo CTEM DEV52**) is a separate server that has
  nothing to do with the plugin. Turn it off while testing so you know which tools you're calling.

Environments come from `environments.json` in the plugin root, plus `~/.config/unizo-ctem-mcp/environments.json` (or
`$UNIZO_CTEM_ENVIRONMENTS_FILE`). The active environment is saved in `~/.config/unizo-ctem-mcp/active-environment.json`.

## Step 0: Prerequisites

```bash
uv --version            # must be on PATH; if missing: curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/projects/Unizo-CTEM/ctem-claude-plugin
python3 -m json.tool environments.json >/dev/null && echo "environments.json OK"
cd mcp-server && uv run pytest && cd ..     # unit tests for the local MCP server
```

## Step 1: Reset everything

Close Claude Code, then run in a terminal:

```bash
cd ~/projects/Unizo-CTEM/ctem-claude-plugin
uv run --quiet --project mcp-server unizo-ctem-mcp env off      # clears active env and removes unizo-ctem-cloud
uv run --quiet --project mcp-server unizo-ctem-mcp logout       # clears gateway SSO tokens
claude mcp remove unizo-ctem-cloud -s user 2>/dev/null          # in case it's still there
claude plugin uninstall unizo-ctem@unizo-ctem
claude plugin marketplace remove unizo-ctem
rm -rf ~/.config/unizo-ctem-mcp                                 # remaining state (active env, tokens)
```

> The last line also deletes `~/.config/unizo-ctem-mcp/environments.json`, if you have one. Back it up first.

Turn off any claude.ai CTEM connector (claude.ai → Settings → Connectors).

Check that everything is gone:

```bash
claude plugin list; claude mcp list; ls ~/.config/unizo-ctem-mcp 2>&1
```

## Step 2: Install the plugin

```bash
claude plugin marketplace add ~/projects/Unizo-CTEM/ctem-claude-plugin
claude plugin install unizo-ctem@unizo-ctem
```

To test the GitHub install path instead: `/plugin marketplace add Unizo-CTEM/ctem-claude-plugin`.

## Step 3: Check that the plugin loads

Start `claude`, then:

1. `/mcp` shows `plugin:unizo-ctem:unizo-ctem` as **connected**, with tools `unizo_ctem_status`, `unizo_ctem_login`, and `unizo_ctem_logout`.
2. `/unizo-ctem:unizo-ctem-setup` asks where your environments file is. That's expected with nothing set up; continue
   with step 4.

## Step 4: Pick the first environment (demo)

1. `/unizo-ctem:unizo-ctem-setup`, choose **Bundled environments**. It lists `demo` and `dev52` and asks which to use.
2. Pick `demo`. It reports the gateway, SSO issuer, and remote MCP URL.
3. **Restart Claude Code.**

## Step 5: Gateway login (local plugin server)

1. `/unizo-ctem:unizo-ctem-setup` shows auth mode `sso`, not signed in.
2. Let it call `unizo_ctem_login`, open the URL it gives you, and sign in (`demo.unizo.ai/realms/ctem`).
3. Run `/unizo-ctem:unizo-ctem-setup` again. It shows you signed in, the gateway reachable, and the environment as `demo`.

## Step 6: Remote server login (`unizo-ctem-cloud`)

1. `/mcp` → `unizo-ctem-cloud` shows **Needs authentication**. Choose **Authenticate** and finish the browser login.
2. `/mcp` → `unizo-ctem-cloud` → **View tools** lists the CTEM tools.
3. Ask Claude: *"Call unizo-ctem-cloud ping and get_my_context"*. It returns your demo user and tenant.

## Step 7: Switch to dev52

1. `/unizo-ctem:unizo-ctem-setup dev52`
2. **Restart Claude Code.**
3. `/unizo-ctem:unizo-ctem-setup` shows the API URL `https://dev52.unizo.ai`. Sign in again when asked. Each realm has its own
   login.
4. `/mcp` → `unizo-ctem-cloud` → **Authenticate**. Switching signs `unizo-ctem-cloud` out whenever its URL or client ID
   changes.
5. *"Call unizo-ctem-cloud get_my_context"* returns your dev52 context. That confirms the switch worked.

## Step 8: Switch back and turn off

1. `/unizo-ctem:unizo-ctem-setup demo`, restart, and confirm that `/unizo-ctem:unizo-ctem-setup` shows demo again.
2. `uv run --quiet --project mcp-server unizo-ctem-mcp env off` in a terminal, restart. `unizo-ctem-cloud` is gone from `/mcp`, and `/unizo-ctem:unizo-ctem-setup` is back to "not
   configured".

## Step 9: Check the other plugin pieces

- Paste a CVE or scanner finding and ask *"triage this"*. This should run the `exposure-triage` agent.

## Useful commands

```bash
# Environment switcher from a terminal (what /unizo-ctem:unizo-ctem-setup runs)
uv run --quiet --project mcp-server unizo-ctem-mcp env [list | current | use <name> [--force] | off]

# Inspect or recreate the remote server registration
claude mcp get unizo-ctem-cloud
claude mcp remove unizo-ctem-cloud -s user && uv run --quiet --project mcp-server unizo-ctem-mcp env use <name>
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `plugin:unizo-ctem:unizo-ctem` failed in `/mcp` | `uv` is on PATH. Run `uv run --project mcp-server unizo-ctem-mcp env list` by hand to see the error. |
| `env` says `not valid JSON` | `python3 -m json.tool environments.json`. A missing comma between environments is the usual cause. |
| `unizo-ctem-cloud` missing after `use` | `claude mcp get unizo-ctem-cloud`, then rerun `use <name>`. Use `--force` only if you added `unizo-ctem-cloud` by hand. |
| `SEP-2352: stored OAuth credential has no 'issuer' stamp` | An old `unizo-ctem-cloud` token is still stored. It doesn't block anything. If sign-in acts strangely, use `/mcp` → `unizo-ctem-cloud` → **Clear authentication** and sign in again. |
| SSO redirect error | The IdP client must allow `http://localhost:8765/callback`. |
| Tools still show the old environment | You didn't restart Claude Code after `use`. |
