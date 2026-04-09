"""
tests/unit/test_mcp_registry.py — MCP 注册表测试 (s19)
"""

from __future__ import annotations

import json

import pytest

from hello_agents.mcp.client import MCPClient, MCPTool, MCPResult
from hello_agents.mcp.registry import MCPRegistry


class TestMCPClient:
    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        client = MCPClient("test", transport="stdio")
        assert not client.is_connected
        await client.connect()
        assert client.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected(self):
        client = MCPClient("test")
        await client.connect()
        await client.disconnect()
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_list_tools_when_not_connected(self):
        client = MCPClient("test")
        tools = await client.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_returns_stub_tools(self):
        client = MCPClient("test")
        await client.connect()
        client.add_stub_tool(MCPTool("read_file", "Reads a file"))
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_call_tool_not_connected_returns_error(self):
        client = MCPClient("test")
        result = await client.call_tool("read_file", {"path": "/tmp/x"})
        assert not result.success
        assert "Not connected" in result.error

    @pytest.mark.asyncio
    async def test_call_tool_stub_returns_not_implemented(self):
        client = MCPClient("test")
        await client.connect()
        result = await client.call_tool("read_file", {"path": "/tmp/x"})
        assert not result.success  # stub doesn't implement

    def test_mcp_tool_to_openai_schema(self):
        tool = MCPTool("read_file", "Reads a file", {"type": "object"})
        schema = tool.to_openai_schema(prefix="mcp_fs_")
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "mcp_fs_read_file"
        assert schema["function"]["description"] == "Reads a file"

    def test_mcp_result_success_to_json(self):
        result = MCPResult(success=True, data={"content": "hello"})
        d = json.loads(result.to_json())
        assert "result" in d

    def test_mcp_result_error_to_json(self):
        result = MCPResult(success=False, data=None, error="something failed")
        d = json.loads(result.to_json())
        assert "error" in d


class TestMCPRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self):
        reg = MCPRegistry()
        client = MCPClient("fs", transport="stdio")
        reg.register("fs", client)
        assert reg.get_client("fs") is client

    @pytest.mark.asyncio
    async def test_health_check(self):
        reg = MCPRegistry()
        client = MCPClient("fs")
        await client.connect()
        reg.register("fs", client)
        health = await reg.health_check()
        assert health["fs"] is True

    @pytest.mark.asyncio
    async def test_all_tools(self):
        reg = MCPRegistry()
        client = MCPClient("fs")
        await client.connect()
        client.add_stub_tool(MCPTool("read_file", "Reads a file"))
        reg.register("fs", client)
        tools = await reg.all_tools()
        assert "fs" in tools
        assert len(tools["fs"]) == 1

    @pytest.mark.asyncio
    async def test_discover_no_config(self, tmp_path):
        reg = MCPRegistry()
        count = await reg.discover(config_path=tmp_path / "nonexistent.json")
        assert count == 0

    @pytest.mark.asyncio
    async def test_discover_with_config(self, tmp_path):
        config_path = tmp_path / "mcp_servers.json"
        config = {"test_server": {"transport": "stdio", "cmd": "echo"}}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        reg = MCPRegistry()
        count = await reg.discover(config_path=config_path)
        assert count == 1
        assert "test_server" in reg.server_names()

    def test_server_names_empty(self):
        reg = MCPRegistry()
        assert reg.server_names() == []
