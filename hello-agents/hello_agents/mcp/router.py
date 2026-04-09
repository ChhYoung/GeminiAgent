"""
mcp/router.py — MCP 工具路由器 (s19)

将 MCPRegistry 中的工具桥接到 ToolRegistry，
工具名使用 mcp:{server}/{tool} 命名规范。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hello_agents.mcp.client import MCPClient
    from hello_agents.mcp.registry import MCPRegistry
    from hello_agents.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class _MCPToolHandler:
    """单个 MCP 工具的 dispatch handler，适配 ToolRegistry 接口。"""

    TOOL_NAMES: set[str]

    def __init__(self, client: "MCPClient", tool_name: str, schema_name: str) -> None:
        self._client = client
        self._tool_name = tool_name
        self.TOOL_NAMES = {schema_name}

    def dispatch(self, tool_call: Any) -> str:
        import asyncio
        import json as _json

        args = _json.loads(tool_call.function.arguments or "{}")
        # 同步调用异步方法（在非 async 上下文中）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                future = concurrent.futures.Future()

                async def _call():
                    return await self._client.call_tool(self._tool_name, args)

                asyncio.ensure_future(_call()).add_done_callback(
                    lambda f: future.set_result(f.result())
                )
                result = future.result(timeout=10)
            else:
                result = loop.run_until_complete(self._client.call_tool(self._tool_name, args))
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return result.to_json()


class MCPRouter:
    """
    MCP 工具路由器：将 MCPRegistry 工具桥接到 ToolRegistry。

    用法：
        router = MCPRouter()
        schemas = await router.bridge(mcp_registry, tool_registry)
    """

    async def bridge(
        self,
        mcp_registry: "MCPRegistry",
        tool_registry: "ToolRegistry",
    ) -> list[dict]:
        """
        发现 MCP 工具并注册到 tool_registry。

        Returns:
            注册成功的 OpenAI tool schema 列表
        """
        schemas: list[dict] = []
        all_tools = await mcp_registry.all_tools()

        for server_name, tools in all_tools.items():
            client = mcp_registry.get_client(server_name)
            if client is None:
                continue
            for tool in tools:
                prefixed = f"mcp_{server_name}_{tool.name}"
                schema = tool.to_openai_schema(prefix=f"mcp_{server_name}_")
                handler = _MCPToolHandler(client, tool.name, prefixed)
                tool_registry.register_handler(handler, [schema])
                schemas.append(schema)
                logger.info("Bridged MCP tool: %s → %s", tool.name, prefixed)

        return schemas
