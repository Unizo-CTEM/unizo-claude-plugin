# Unizo plugin: developer test guide

This guide tests the plugin from a clean state on a developer machine: install it from this checkout, sign in to a
hosted environment, and switch between environments. For configuration, administrator setup, and the fake deployment,
see [SETUP_AND_TESTING.md](SETUP_AND_TESTING.md).

## How the pieces fit

```
plugin:unizo:unizo   →  local process (uv run unizo-mcp) →  Unizo gateway API   [part of the plugin]
unizo-cloud         →  https://<env>/mcp               (direct, OAuth)      [registered by /unizo:unizo-plugin-configure, runs on its own]
```

- **`plugin:unizo:unizo`** is the plugin's local stdio server. It has only `unizo_status`, `unizo_login`, and
  `unizo_logout`, and signs in to the gateway with SSO.
- **`unizo-cloud`** is the remote Unizo MCP server, where the Unizo tools are. `/unizo:unizo-plugin-configure <environments.json> <name>` adds it to
  your Claude Code **user** config (`~/.claude.json`). After that, Claude Code connects to it directly. Calls don't
  go through the plugin. It stays registered even if the plugin is turned off, until `unizo-mcp env off` or
  `claude mcp remove unizo-cloud -s user`.
- A claude.ai connector for the same backend (for example **Unizo DEV52**) is a separate server that has
  nothing to do with the plugin. Turn it off while testing so you know which tools you're calling.

Environments come only from the file you pass (the plugin ships none and reads none by default). This guide uses
`~/unizo-envs.json`, holding `demo` and `dev52`. The active environment is saved in
`~/.config/unizo-mcp/active-environment.json`, together with the path of the file it came from.

## Step 0: Prerequisites

```bash
uv --version            # must be on PATH; if missing: curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/projects/Unizo-CTEM/ctem-claude-plugin
python3 -m json.tool ~/unizo-envs.json >/dev/null && echo "unizo-envs.json OK"
cd mcp-server && uv run pytest && cd ..     # unit tests for the local MCP server
```

## Step 1: Reset everything

Close Claude Code, then run in a terminal:

```bash
cd ~/projects/Unizo-CTEM/ctem-claude-plugin
uv run --quiet --project mcp-server unizo-mcp env off      # clears active env and removes unizo-cloud
uv run --quiet --project mcp-server unizo-mcp logout       # clears gateway SSO tokens
claude mcp remove unizo-cloud -s user 2>/dev/null          # in case it's still there
claude plugin uninstall unizo@unizo
claude plugin marketplace remove unizo
rm -rf ~/.config/unizo-mcp                                 # remaining state (active env, tokens)
```

Turn off any claude.ai Unizo connector (claude.ai → Settings → Connectors).

Check that everything is gone:

```bash
claude plugin list; claude mcp list; ls ~/.config/unizo-mcp 2>&1
```

## Step 2: Install the plugin

```bash
claude plugin marketplace add ~/projects/Unizo-CTEM/ctem-claude-plugin
claude plugin install unizo@unizo
```

To test the GitHub install path instead: `/plugin marketplace add Unizo-CTEM/ctem-claude-plugin`.

## Step 3: Check that the plugin loads

Start `claude`, then:

1. `/mcp` shows `plugin:unizo:unizo` as **connected**, with tools `unizo_status`, `unizo_login`, and `unizo_logout`.
2. `/unizo:unizo-plugin-configure` asks where your environments file is. That's expected with nothing set up; continue
   with step 4.

## Step 4: Pick the first environment (demo)

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json`. It lists `demo` and `dev52` and asks which to use.
2. Pick `demo`. It reports the gateway, SSO issuer, and remote MCP URL.
3. **Restart Claude Code.**

## Step 5: Gateway login (local plugin server)

1. `/unizo:unizo-plugin-configure` shows auth mode `sso`, not signed in.
2. Let it call `unizo_login`, open the URL it gives you, and sign in (`demo.unizo.ai/realms/ctem`).
3. Run `/unizo:unizo-plugin-configure` again. It shows you signed in, the gateway reachable, and the environment as `demo`.

## Step 6: Remote server login (`unizo-cloud`)

1. `/mcp` → `unizo-cloud` shows **Needs authentication**. Choose **Authenticate** and finish the browser login.
2. `/mcp` → `unizo-cloud` → **View tools** lists the Unizo tools.
3. Ask Claude: *"Call unizo-cloud ping and get_my_context"*. It returns your demo user and tenant.

## Step 7: Switch to dev52

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json dev52`
2. **Restart Claude Code.**
3. `/unizo:unizo-plugin-configure` shows the API URL `https://dev52.unizo.ai`. Sign in again when asked. Each realm has its own
   login.
4. `/mcp` → `unizo-cloud` → **Authenticate**. Switching signs `unizo-cloud` out whenever its URL or client ID
   changes.
5. *"Call unizo-cloud get_my_context"* returns your dev52 context. That confirms the switch worked.

## Step 8: Switch back and turn off

1. `/unizo:unizo-plugin-configure ~/unizo-envs.json demo`, restart, and confirm that `/unizo:unizo-plugin-configure` shows demo again.
2. `uv run --quiet --project mcp-server unizo-mcp env off` in a terminal, restart. `unizo-cloud` is gone from `/mcp`, and `/unizo:unizo-plugin-configure` is back to "not
   configured".

## Step 9: Check the other plugin pieces

- Paste a CVE or scanner finding and ask *"triage this"*. This should run the `exposure-triage` agent.

## Useful commands

```bash
# Environment switcher from a terminal (what /unizo:unizo-plugin-configure runs)
uv run --quiet --project mcp-server unizo-mcp env [list --file <path> | current | use <name> --file <path> [--force] | off]

# Inspect or recreate the remote server registration
claude mcp get unizo-cloud
claude mcp remove unizo-cloud -s user && uv run --quiet --project mcp-server unizo-mcp env use <name> --file ~/unizo-envs.json
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `plugin:unizo:unizo` failed in `/mcp` | `uv` is on PATH. Run `uv run --project mcp-server unizo-mcp env current` by hand to see the error. |
| `env` says `not valid JSON` | `python3 -m json.tool ~/unizo-envs.json`. A missing comma between environments is the usual cause. |
| `unizo-cloud` missing after `use` | `claude mcp get unizo-cloud`, then rerun `use <name>`. Use `--force` only if you added `unizo-cloud` by hand. |
| `SEP-2352: stored OAuth credential has no 'issuer' stamp` | An old `unizo-cloud` token is still stored. It doesn't block anything. If sign-in acts strangely, use `/mcp` → `unizo-cloud` → **Clear authentication** and sign in again. |
| SSO redirect error | The IdP client must allow `http://localhost:8765/callback`. |
| Tools still show the old environment | You didn't restart Claude Code after `use`. |
