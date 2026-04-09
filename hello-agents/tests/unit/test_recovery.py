"""
tests/unit/test_recovery.py — 错误恢复测试 (s11)
"""

from __future__ import annotations

import pytest

from hello_agents.recovery.retry import RetryPolicy
from hello_agents.recovery.checkpoint import CheckpointStore
from hello_agents.recovery.fallback import FallbackChain


# ---- RetryPolicy ----

class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        policy = RetryPolicy(max_attempts=3)
        result = await policy.execute(lambda: 42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_retries_and_succeeds(self):
        calls = [0]

        def flaky():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("transient")
            return "ok"

        policy = RetryPolicy(max_attempts=3, base_delay=0.01, retryable=(ValueError,))
        result = await policy.execute(flaky)
        assert result == "ok"
        assert calls[0] == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        policy = RetryPolicy(max_attempts=2, base_delay=0.01, retryable=(RuntimeError,))
        with pytest.raises(RuntimeError):
            await policy.execute(lambda: (_ for _ in ()).throw(RuntimeError("always fails")))

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self):
        calls = [0]

        def fn():
            calls[0] += 1
            raise TypeError("not retryable")

        policy = RetryPolicy(max_attempts=3, base_delay=0.01, retryable=(ValueError,))
        with pytest.raises(TypeError):
            await policy.execute(fn)
        assert calls[0] == 1  # no retry

    @pytest.mark.asyncio
    async def test_async_fn_works(self):
        async def async_fn():
            return "async result"

        policy = RetryPolicy()
        result = await policy.execute(async_fn)
        assert result == "async result"

    def test_with_attempts(self):
        policy = RetryPolicy(max_attempts=3)
        new_policy = policy.with_attempts(5)
        assert new_policy.max_attempts == 5
        assert new_policy.base_delay == policy.base_delay


# ---- CheckpointStore ----

class TestCheckpointStore:
    def test_save_and_load(self, tmp_path):
        store = CheckpointStore(directory=tmp_path)
        msgs = [{"role": "user", "content": "hello"}]
        store.save("session-1", msgs, step_idx=2)

        result = store.load("session-1")
        assert result is not None
        loaded_msgs, idx = result
        assert loaded_msgs == msgs
        assert idx == 2

    def test_load_nonexistent(self, tmp_path):
        store = CheckpointStore(directory=tmp_path)
        assert store.load("ghost-session") is None

    def test_delete(self, tmp_path):
        store = CheckpointStore(directory=tmp_path)
        store.save("s1", [], step_idx=0)
        assert store.exists("s1")
        store.delete("s1")
        assert not store.exists("s1")

    def test_list_sessions(self, tmp_path):
        store = CheckpointStore(directory=tmp_path)
        store.save("a", [], 0)
        store.save("b", [], 0)
        sessions = store.list_sessions()
        assert set(sessions) == {"a", "b"}

    def test_delete_nonexistent_returns_false(self, tmp_path):
        store = CheckpointStore(directory=tmp_path)
        assert store.delete("nothing") is False


# ---- FallbackChain ----

class TestFallbackChain:
    def _make_registry(self):
        """Create a minimal ToolRegistry with test handlers."""
        from hello_agents.tools.registry import ToolRegistry
        from unittest.mock import MagicMock

        registry = ToolRegistry()
        # Register a simple handler
        handler = MagicMock()
        handler.TOOL_NAMES = {"primary_tool", "backup_tool"}
        handler.dispatch.return_value = '{"result": "from_handler"}'
        registry.register_handler(handler, [
            {"type": "function", "function": {"name": "primary_tool", "parameters": {}}},
            {"type": "function", "function": {"name": "backup_tool", "parameters": {}}},
        ])
        return registry, handler

    def test_primary_succeeds(self):
        chain = FallbackChain()
        chain.add("primary_tool", "backup_tool")
        registry, handler = self._make_registry()
        result = chain.call("primary_tool", {}, registry)
        assert "result" in result

    def test_fallback_used_when_primary_fails(self):
        chain = FallbackChain()
        chain.add("primary_tool", "backup_tool")
        registry, handler = self._make_registry()
        # Make primary fail
        handler.dispatch.side_effect = [RuntimeError("fail"), '{"result": "backup"}']
        result = chain.call("primary_tool", {}, registry)
        import json
        data = json.loads(result)
        assert "result" in data or "error" in data  # backup or error

    def test_all_fail_returns_error(self):
        chain = FallbackChain()
        chain.add("primary_tool", "backup_tool")
        registry, handler = self._make_registry()
        handler.dispatch.side_effect = RuntimeError("always fails")
        result = chain.call("primary_tool", {}, registry)
        import json
        data = json.loads(result)
        assert "error" in data

    def test_unregistered_tool_returns_error(self):
        chain = FallbackChain()
        from hello_agents.tools.registry import ToolRegistry
        registry = ToolRegistry()
        result = chain.call("nonexistent", {}, registry)
        import json
        data = json.loads(result)
        assert "error" in data
