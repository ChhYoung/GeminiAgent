"""
mcp/client.py — MCP 客户端 (s19)

抽象 MCP 协议客户端接口，支持 stdio / SSE / WebSocket 三种传输。
当 mcp 包未安装时，以 stub 模式运行（工具列表为空）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """MCP 服务暴露的工具描述。"""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)

    def to_openai_schema(self, prefix: str = "") -> dict:
        """转换为 OpenAI function schema 格式。"""
        fname = f"{prefix}{self.name}" if prefix else self.name
        return {
            "type": "function",
            "function": {
                "name": fname,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass
class MCPResult:
    success: bool
    data: Any
    error: str = ""

    def to_json(self) -> str:
        if self.success:
            return json.dumps({"result": self.data})
        return json.dumps({"error": self.error})


class MCPClient:
    """
    MCP 客户端（stub 实现）。

    实际项目中可扩展为真正的 stdio/SSE/WebSocket 客户端。
    当前版本为测试友好的 stub 实现。

    用法：
        client = MCPClient("filesystem", transport="stdio", endpoint="...")
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/tmp/x.txt"})
    """

    def __init__(
        self,
        server_name: str,
        transport: str = "stdio",
        endpoint: str = "",
    ) -> None:
        self.server_name = server_name
        self.transport = transport
        self.endpoint = endpoint
        self._connected = False
        self._tools: list[MCPTool] = []

    async def connect(self) -> None:
        """连接到 MCP 服务器（stub：标记为已连接）。"""
        self._connected = True
        logger.info("MCPClient '%s' connected (transport=%s)", self.server_name, self.transport)

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("MCPClient '%s' disconnected", self.server_name)

    async def list_tools(self) -> list[MCPTool]:
        """获取服务器暴露的工具列表（stub：返回内部工具列表）。"""
        if not self._connected:
            logger.warning("MCPClient '%s' not connected", self.server_name)
            return []
        return list(self._tools)

    async def call_tool(self, tool_name: str, args: dict) -> MCPResult:
        """调用远程工具（stub：返回未实现错误）。"""
        if not self._connected:
            return MCPResult(success=False, data=None, error="Not connected")
        logger.info("MCPClient '%s': calling %s(%s)", self.server_name, tool_name, args)
        return MCPResult(success=False, data=None, error=f"Tool '{tool_name}' not implemented in stub")

    def add_stub_tool(self, tool: MCPTool) -> None:
        """测试用：向 stub 客户端添加工具。"""
        self._tools.append(tool)

    @property
    def is_connected(self) -> bool:
        return self._connected
