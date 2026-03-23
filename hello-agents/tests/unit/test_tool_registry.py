"""
UT: tools/registry.py — ToolRegistry 注册/分发
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from hello_agents.tools.registry import ToolRegistry


def _make_schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Tool {name}",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _make_handler(names: set[str], return_value: str = '{"ok": true}'):
    handler = MagicMock()
    handler.TOOL_NAMES = names
    handler.dispatch.return_value = return_value
    return handler


def _make_tool_call(name: str, args: str = "{}"):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = args
    tc.id = "call_001"
    return tc


# ---------------------------------------------------------------------------
# register_handler / get_schemas
# ---------------------------------------------------------------------------

class TestRegisterAndSchemas:
    def test_register_single_handler(self):
        registry = ToolRegistry()
        handler = _make_handler({"my_tool"})
        registry.register_handler(handler, [_make_schema("my_tool")])
        schemas = registry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "my_tool"

    def test_register_multiple_handlers(self):
        registry = ToolRegistry()
        h1 = _make_handler({"tool_a"})
        h2 = _make_handler({"tool_b", "tool_c"})
        registry.register_handler(h1, [_make_schema("tool_a")])
        registry.register_handler(h2, [_make_schema("tool_b"), _make_schema("tool_c")])
        schemas = registry.get_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b", "tool_c"}

    def test_get_schemas_returns_copy(self):
        registry = ToolRegistry()
        handler = _make_handler({"t"})
        registry.register_handler(handler, [_make_schema("t")])
        schemas = registry.get_schemas()
        schemas.append({"extra": "item"})
        # 原始列表未被修改
        assert len(registry.get_schemas()) == 1

    def test_empty_registry(self):
        registry = ToolRegistry()
        assert registry.get_schemas() == []


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_dispatch_routes_to_correct_handler(self):
        registry = ToolRegistry()
        h1 = _make_handler({"tool_a"})
        h2 = _make_handler({"tool_b"})
        registry.register_handler(h1, [_make_schema("tool_a")])
        registry.register_handler(h2, [_make_schema("tool_b")])

        tc_a = _make_tool_call("tool_a")
        registry.dispatch(tc_a)
        h1.dispatch.assert_called_once_with(tc_a)
        h2.dispatch.assert_not_called()

    def test_dispatch_returns_handler_result(self):
        registry = ToolRegistry()
        handler = _make_handler({"my_tool"}, return_value='{"result": 42}')
        registry.register_handler(handler, [_make_schema("my_tool")])
        result = registry.dispatch(_make_tool_call("my_tool"))
        assert result == '{"result": 42}'

    def test_dispatch_unknown_tool_returns_error(self):
        registry = ToolRegistry()
        result = registry.dispatch(_make_tool_call("ghost_tool"))
        data = json.loads(result)
        assert "error" in data
        assert "ghost_tool" in data["error"]

    def test_dispatch_calls_handler_with_tool_call_object(self):
        registry = ToolRegistry()
        handler = _make_handler({"t"})
        registry.register_handler(handler, [_make_schema("t")])
        tc = _make_tool_call("t", args='{"key": "val"}')
        registry.dispatch(tc)
        handler.dispatch.assert_called_once_with(tc)


# ---------------------------------------------------------------------------
# has_tool
# ---------------------------------------------------------------------------

class TestHasTool:
    def test_registered_tool_found(self):
        registry = ToolRegistry()
        handler = _make_handler({"exists"})
        registry.register_handler(handler, [_make_schema("exists")])
        assert registry.has_tool("exists") is True

    def test_unregistered_tool_not_found(self):
        registry = ToolRegistry()
        assert registry.has_tool("phantom") is False
