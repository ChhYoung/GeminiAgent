"""
tests/unit/test_hooks.py — Hook 系统测试 (s08)
"""

from __future__ import annotations

import pytest

from hello_agents.hooks.events import HookEvent
from hello_agents.hooks.registry import HookRegistry


class TestHookRegistry:
    @pytest.mark.asyncio
    async def test_register_and_fire(self):
        reg = HookRegistry()
        calls = []
        reg.on(HookEvent.PRE_TOOL, lambda p: calls.append(p))
        await reg.fire(HookEvent.PRE_TOOL, {"tool": "search_memory"})
        assert len(calls) == 1
        assert calls[0]["tool"] == "search_memory"

    @pytest.mark.asyncio
    async def test_multiple_hooks_same_event(self):
        reg = HookRegistry()
        calls = []
        reg.on(HookEvent.POST_LLM, lambda p: calls.append("A"))
        reg.on(HookEvent.POST_LLM, lambda p: calls.append("B"))
        await reg.fire(HookEvent.POST_LLM, {})
        assert calls == ["A", "B"]

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_crash(self):
        reg = HookRegistry()
        reg.on(HookEvent.ON_ERROR, lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        # Should not raise
        await reg.fire(HookEvent.ON_ERROR, {"error": "something"})

    @pytest.mark.asyncio
    async def test_async_hook(self):
        reg = HookRegistry()
        results = []

        async def async_hook(payload):
            results.append(payload.get("key"))

        reg.on(HookEvent.ON_REPLY, async_hook)
        await reg.fire(HookEvent.ON_REPLY, {"key": "value"})
        assert results == ["value"]

    def test_listener_count(self):
        reg = HookRegistry()
        assert reg.listener_count(HookEvent.PRE_TOOL) == 0
        reg.on(HookEvent.PRE_TOOL, lambda p: None)
        assert reg.listener_count(HookEvent.PRE_TOOL) == 1

    def test_off_removes_hook(self):
        reg = HookRegistry()
        fn = lambda p: None
        reg.on(HookEvent.PRE_LLM, fn)
        removed = reg.off(HookEvent.PRE_LLM, fn)
        assert removed is True
        assert reg.listener_count(HookEvent.PRE_LLM) == 0

    def test_off_nonexistent_returns_false(self):
        reg = HookRegistry()
        assert reg.off(HookEvent.PRE_LLM, lambda p: None) is False

    def test_clear_specific_event(self):
        reg = HookRegistry()
        reg.on(HookEvent.PRE_TOOL, lambda p: None)
        reg.on(HookEvent.POST_TOOL, lambda p: None)
        reg.clear(HookEvent.PRE_TOOL)
        assert reg.listener_count(HookEvent.PRE_TOOL) == 0
        assert reg.listener_count(HookEvent.POST_TOOL) == 1

    def test_clear_all(self):
        reg = HookRegistry()
        reg.on(HookEvent.PRE_TOOL, lambda p: None)
        reg.on(HookEvent.PRE_LLM, lambda p: None)
        reg.clear()
        assert reg.listener_count(HookEvent.PRE_TOOL) == 0
        assert reg.listener_count(HookEvent.PRE_LLM) == 0

    @pytest.mark.asyncio
    async def test_no_hooks_fire_silently(self):
        reg = HookRegistry()
        # Should not raise when no hooks registered
        await reg.fire(HookEvent.POST_TOOL, {"result": "ok"})

    def test_all_event_types_exist(self):
        for evt in [
            HookEvent.PRE_TOOL, HookEvent.POST_TOOL,
            HookEvent.PRE_LLM, HookEvent.POST_LLM,
            HookEvent.ON_ERROR, HookEvent.ON_REPLY,
        ]:
            assert isinstance(evt.value, str)
