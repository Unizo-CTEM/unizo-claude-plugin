#!/usr/bin/env bash
# Headless smoke test: drives real Claude Code (claude -p) against the installed unizo-ctem plugin.
#
# Prerequisites:
#   - the plugin is installed and configured (see docs/SETUP_AND_TESTING.md), e.g. against fake_stack.py
#   - you are signed in to Claude Code (this uses your account and counts toward usage)
#
# Usage: mcp-server/tests/e2e/claude_smoke.sh [output-dir]
#
# No real browser tab is opened: BROWSER points at a helper that "visits" the sign-in URL with curl, which is
# enough for fake_stack.py (it signs in instantly). Against a real IdP, unset FAKE_BROWSER=1 to use your browser.
set -euo pipefail

OUT="${1:-$(mktemp -d -t ctem-smoke)}"
mkdir -p "$OUT"
TOOLS="mcp__plugin_unizo-ctem_unizo-ctem__unizo_ctem_status,mcp__plugin_unizo-ctem_unizo-ctem__unizo_ctem_login,mcp__plugin_unizo-ctem_unizo-ctem__unizo_ctem_logout"
WORK="$(mktemp -d -t ctem-smoke-work)"   # neutral directory, so no project .mcp.json interferes

if [[ "${FAKE_BROWSER:-1}" == "1" ]]; then
  cat > "$OUT/browser.sh" <<'EOF'
#!/bin/sh
curl -s -L -o /dev/null "$1"
EOF
  chmod +x "$OUT/browser.sh"
  export BROWSER="$OUT/browser.sh %s"
fi

run() {  # run <name> <prompt>
  local name="$1" prompt="$2"
  echo "=== $name: $prompt"
  (cd "$WORK" && claude -p "$prompt" --allowedTools "$TOOLS" --max-turns 8 \
     --output-format stream-json --verbose < /dev/null > "$OUT/$name.jsonl" 2>&1) || true
  python3 - "$OUT/$name.jsonl" <<'EOF'
import json, sys
for line in open(sys.argv[1]):
    try:
        m = json.loads(line)
    except ValueError:
        continue
    if m.get("type") == "assistant":
        for c in m["message"]["content"]:
            if c["type"] == "tool_use" and c["name"].startswith("mcp__plugin_unizo-ctem"):
                print("  tool:", c["name"].split("__")[-1], json.dumps(c["input"]))
    elif m.get("type") == "result":
        print("  answer:", (m.get("result") or "").strip().replace("\n", "\n          "))
EOF
  echo
}

run 01-setup   "/unizo-ctem:unizo-ctem-plugin-configure"
run 02-status  "Is my CTEM connection healthy? Who am I signed in as?"
run 03-relogin "Sign me out of CTEM, then sign me back in."

echo "Transcripts: $OUT"
