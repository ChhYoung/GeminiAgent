"""
mcp/registry.py — MCP 服务器注册表 (s19)

管理多个 MCP 客户端，支持动态发现和健康检查。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hello_agents.mcp.client import MCPClient, MCPTool

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path.home() / ".agent" / "mcp_servers.json"


class MCPRegistry:
    """
    MCP 服务注册表。

    用法：
        registry = MCPRegistry()
        await registry.discover()          # 读取配置文件
        ok = await registry.health_check()
        tools = registry.all_tools()
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    def register(self, name: str, client: MCPClient) -> None:
        self._clients[name] = client

    async def discover(self, config_path: str | Path = _DEFAULT_CONFIG) -> int:
        """
        从配置文件发现并连接 MCP 服务器。

        配置格式：
            {"name": {"transport": "stdio", "cmd": "..."}}

        Returns:
            成功连接的服务器数量
        """
        path = Path(config_path)
        if not path.exists():
            logger.debug("No MCP config at %s", path)
            return 0

        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read MCP config: %s", exc)
            return 0

        count = 0
        for name, opts in config.items():
            transport = opts.get("transport", "stdio")
            endpoint = opts.get("endpoint", opts.get("cmd", ""))
            client = MCPClient(name, transport=transport, endpoint=endpoint)
            try:
                await client.connect()
                self._clients[name] = client
                count += 1
            except Exception as exc:
                logger.warning("MCP server '%s' connect failed: %s", name, exc)

        logger.info("MCPRegistry: %d/%d servers connected", count, len(config))
        return count

    async def health_check(self) -> dict[str, bool]:
        """检查所有注册服务器的健康状态。"""
        result: dict[str, bool] = {}
        for name, client in self._clients.items():
            result[name] = client.is_connected
        return result

    async def all_tools(self) -> dict[str, list[MCPTool]]:
        """获取所有服务器的工具列表。"""
        out: dict[str, list[MCPTool]] = {}
        for name, client in self._clients.items():
            out[name] = await client.list_tools()
        return out

    def get_client(self, server_name: str) -> MCPClient | None:
        return self._clients.get(server_name)

    def server_names(self) -> list[str]:
        return list(self._clients.keys())
