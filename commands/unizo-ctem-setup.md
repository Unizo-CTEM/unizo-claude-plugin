---
description: Check the CTEM plugin's connection to your deployment and walk through setup or SSO sign-in
---

Help the user connect this plugin to their organization's Unizo CTEM deployment (GCP or AWS).

1. Call the `unizo_ctem_status` tool. If the `unizo-ctem` MCP server is not available at all, tell the user to check `/mcp`
   (the server needs `uv` on the `PATH`) and restart Claude Code. Then stop. If the API URL isn't configured, offer
   `/unizo-ctem:unizo-ctem-env` to pick an environment, or `/plugin configure unizo-ctem@unizo-ctem` to set **CTEM API URL**.
2. Summarize the result in a few lines: API URL, auth mode (`static-token`, `sso`, or `none`), who is signed in,
   and whether the gateway is reachable. List any `config_problems` verbatim.
3. Then give exactly one next step:
   - `auth_mode` is `none`: they need either an API token or SSO (issuer URL + client ID, from their identity
     provider admin). Point them to `/plugin configure unizo-ctem@unizo-ctem`, and remind them that changes apply after
     a restart.
   - `auth_mode` is `sso` and not signed in, or the token expired and can't refresh: call `unizo_ctem_login` once. If it
     returns a `login_url`, show it and ask them to finish signing in there.
   - Gateway not reachable: show the `detail` and suggest checking the API URL and network access (VPN, firewall,
     allow-listing) to their deployment.
   - Everything works: say so.
4. Mention the environment: if `environment` is set, say which one is active and the file it came from (the
   plugin options are not used while an environment is active). Users switch with `/unizo-ctem:unizo-ctem-env use <name>`.
5. Mention the remote CTEM MCP server (`unizo-ctem-cloud`). An environment with `remote_mcp` registers it. If its tools
   aren't available, the user signs in to it from `/mcp` → `unizo-ctem-cloud` → Authenticate. If no environment is
   active, there's no remote server: suggest `/unizo-ctem:unizo-ctem-env use demo` or the user's own environment.

Never ask the user to paste tokens or secrets into the chat; secrets belong in `/plugin configure`.

$ARGUMENTS
