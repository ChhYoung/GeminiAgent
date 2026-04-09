"""
tests/unit/test_memory_gc.py — 记忆垃圾回收测试 (s09)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.memory.gc import MemoryGarbageCollector


class TestMemoryGarbageCollector:
    def _make_gc(self) -> MemoryGarbageCollector:
        manager = MagicMock()
        manager.get_working_memory.return_value = MagicMock()
        return MemoryGarbageCollector(manager, min_strength=0.1)

    @pytest.mark.asyncio
    async def test_run_once_no_crash(self):
        gc = self._make_gc()
        deleted = await gc.run_once()
        assert isinstance(deleted, int)
        assert deleted >= 0

    @pytest.mark.asyncio
    async def test_is_not_running_by_default(self):
        gc = self._make_gc()
        assert not gc.is_running

    @pytest.mark.asyncio
    async def test_start_background_sets_running(self):
        gc = self._make_gc()
        await gc.start_background(interval_s=999)
        assert gc.is_running
        await gc.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        gc = self._make_gc()
        await gc.start_background(interval_s=999)
        await gc.stop()
        assert not gc.is_running

    @pytest.mark.asyncio
    async def test_double_stop_safe(self):
        gc = self._make_gc()
        await gc.stop()  # Stop without ever starting
        assert not gc.is_running

    @pytest.mark.asyncio
    async def test_run_once_handles_manager_error(self):
        manager = MagicMock()
        manager.get_working_memory.side_effect = RuntimeError("db error")
        gc = MemoryGarbageCollector(manager)
        # Should not raise
        deleted = await gc.run_once()
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_multiple_start_background_calls(self):
        gc = self._make_gc()
        await gc.start_background(interval_s=999)
        first_task = gc._task
        await gc.start_background(interval_s=999)  # second call replaces
        await gc.stop()
        assert not gc.is_running
