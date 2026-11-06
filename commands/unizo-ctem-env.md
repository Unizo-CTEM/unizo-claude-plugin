---
description: List CTEM environments or switch between them (gateway, SSO, and remote MCP server URL + client ID)
argument-hint: "[<path-to-environments.json> | list | current | use <name> | off]"
allowed-tools: Bash(uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env:*)
---

Help the user see or switch their Unizo CTEM environment. Environments are defined in JSON files: the one shipped
with the plugin, plus the user's own `~/.config/unizo-ctem-mcp/environments.json` (or `$UNIZO_CTEM_ENVIRONMENTS_FILE`).

Arguments: `$ARGUMENTS`

**If the argument is a path to an environments file** (anything that isn't `list`, `current`, `use ...` or `off`,
e.g. `~/acme-envs.json` or `./environments.json`), let the user pick from that file:

1. List its environments:

   ```
   uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env list --file <path>
   ```

2. Ask the user which one to use with AskUserQuestion: one option per environment (name as the label, gateway URL
   and description as the description; up to 4 options, the user can type any other name). If the file holds a
   single environment, still confirm before switching.
3. Switch to the chosen one, passing the same file:

   ```
   uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env use <name> --file <path>
   ```

   and report the result as for **use <name>** below.

**Otherwise** run the switcher with Bash, passing the user's arguments through (no arguments means `list`):

```
uv run --quiet --project ${CLAUDE_PLUGIN_ROOT}/mcp-server unizo-ctem-mcp env $ARGUMENTS
```

Then:

- **list**: show the environments as a short table and mark the active one (`*`). If the user seems to want to
  switch, ask which one with AskUserQuestion. Mention they can also run `/unizo-ctem:unizo-ctem-env <path>` to pick
  from their own environments file.
- **use <name>**: report the gateway, SSO issuer, and remote MCP URL + client ID now in effect. Tell the user to
  **restart Claude Code**, then run `/unizo-ctem:unizo-ctem-setup` to sign in to the gateway, and to sign in to the remote server
  with `/mcp` → `unizo-ctem-cloud` → Authenticate. The switch signs the remote server out whenever its URL or client ID
  changes. That's expected.
- **off**: say the plugin options from `/plugin configure unizo-ctem@unizo-ctem` apply again after a restart.
- **An error**: show it verbatim. If no environments file exists or the name is unknown, explain the file format
  with this example and offer to create the user's file:

  ```json
  {
    "environments": {
      "staging": {
        "description": "Acme staging",
        "api_url": "https://ctem-staging.acme.com",
        "sso_issuer": "https://acme.okta.com/oauth2/default",
        "sso_client_id": "0oa-staging-client",
        "remote_mcp": { "url": "https://ctem-staging.acme.com/mcp", "client_id": "ctem-mcp-staging" }
      }
    }
  }
  ```

  If `unizo-ctem-cloud` already exists and this command didn't add it, ask the user before re-running with `--force`.

Never put API tokens or client secrets in an environments file. They belong in `/plugin configure unizo-ctem@unizo-ctem`,
and an environment uses them only if it sets `"use_plugin_secrets": true`.
