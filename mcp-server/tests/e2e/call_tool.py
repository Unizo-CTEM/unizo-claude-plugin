"""Call a tool on the Unizo MCP server directly, without Claude. Reads the same UNIZO_* environment variables.

    uv run --project mcp-server python mcp-server/tests/e2e/call_tool.py                 # unizo_status
    uv run --project mcp-server python mcp-server/tests/e2e/call_tool.py unizo_login '{"wait_seconds": 60}'
    uv run --project mcp-server python mcp-server/tests/e2e/call_tool.py --list

Starts the server in-process through a real MCP client session, so it exercises the same code Claude Code uses.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client

from unizo_mcp.server import build_server


async def main(argv: list[str]) -> int:
    async with Client(build_server()) as client:
        if argv[:1] == ["--list"]:
            for tool in (await client.list_tools()).tools:
                print(f"{tool.name}: {(tool.description or '').splitlines()[0]}")
            return 0
        name = argv[0] if argv else "unizo_status"
        args = json.loads(argv[1]) if len(argv) > 1 else {}
        result = await client.call_tool(name, args)
        for block in result.content:
            text = getattr(block, "text", "")
            try:
                print(json.dumps(json.loads(text), indent=2))
            except ValueError:
                print(text)
        return 1 if result.is_error else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
