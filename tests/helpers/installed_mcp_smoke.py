"""Read-only smoke of an installed MCP's real stdio transport; no source imports."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    config = Path(sys.argv[1])
    executable = Path(sys.executable).parent / "snaplii-mcp"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update(SNAPLII_CONFIG_PATH=str(config), SNAPLII_ALLOW_INSECURE="0",
                       PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring")
    parameters = StdioServerParameters(command=str(executable), env=environment)
    print("Starting installed MCP stdio smoke", file=sys.stderr, flush=True)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP initialize passed", file=sys.stderr, flush=True)
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"snaplii_connect", "snaplii_init", "snaplii_config_show", "snaplii_balance"} <= names
            result = await session.call_tool("snaplii_config_show", {})
            status = json.loads(result.content[0].text)
            assert status["has_valid_token"] is False
            assert status["credential_storage"] == "process memory"
            assert status["next_action"] == {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
            assert not config.exists()
            print(json.dumps({"stdio": "passed", "tools": len(names), "status": "unauthenticated",
                              "memory_recovery": "snaplii_connect", "configuration_created": False}))


asyncio.run(asyncio.wait_for(main(), timeout=20))
