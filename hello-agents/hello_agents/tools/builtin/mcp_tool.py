"""
tools/builtin/mcp_tool.py — MCP 工具透传 (s19)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from hello_agents.mcp.registry import MCPRegistry

MCP_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_mcp_servers",
            "description": "列出已注册的 MCP 服务器和它们的工具",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_mcp",
            "description": "调用指定 MCP 服务器上的工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务器名称"},
                    "tool": {"type": "string", "description": "工具名"},
                    "args": {"type": "object", "description": "工具参数"},
                },
                "required": ["server", "tool"],
            },
        },
    },
]


class MCPToolHandler:
    TOOL_NAMES = {"list_mcp_servers", "call_mcp"}

    def __init__(self, registry: MCPRegistry) -> None:
        self._registry = registry

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        args: dict = json.loads(tool_call.function.arguments or "{}")
        if name == "list_mcp_servers":
            return self._list()
        if name == "call_mcp":
            return self._call(args)
        return json.dumps({"error": f"Unknown MCP tool: {name}"})

    def _list(self) -> str:
        servers = self._registry.server_names()
        return json.dumps({"servers": servers})

    def _call(self, args: dict) -> str:
        client = self._registry.get_client(args["server"])
        if client is None:
            return json.dumps({"error": f"MCP server '{args['server']}' not found"})
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 无法在运行中的 loop 里同步等待，返回提示
                return json.dumps({"error": "Use async context to call MCP tools"})
            result = loop.run_until_complete(client.call_tool(args["tool"], args.get("args", {})))
            return result.to_json()
        except Exception as exc:
            return json.dumps({"error": str(exc)})
