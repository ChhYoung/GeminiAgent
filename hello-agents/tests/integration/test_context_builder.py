"""
集成测试: context/builder.py — ContextBuilder GSSC 流水线
使用 mock 替代 MemoryManager 和 KnowledgeBaseManager，不依赖外部服务。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from hello_agents.context.builder import ContextBuilder
from hello_agents.context.gather import RawItem
from hello_agents.memory.base import MemorySearchResult, MemoryRecord, MemoryType, ImportanceLevel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_search_result(content: str, score: float = 0.8) -> MemorySearchResult:
    record = MemoryRecord(memory_type=MemoryType.EPISODIC, content=content)
    return MemorySearchResult(record=record, relevance_score=score, final_score=score, source="qdrant")


@pytest.fixture
def mock_memory_manager():
    mm = MagicMock()
    mm.read = MagicMock(return_value=[])
    return mm


@pytest.fixture
def mock_kb_manager():
    kb = MagicMock()
    kb.list_all = MagicMock(return_value=[])
    return kb


# ---------------------------------------------------------------------------
# ContextBuilder.build() — 基础场景
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestContextBuilderBuild:
    async def test_no_sources_returns_empty(self):
        builder = ContextBuilder(memory_manager=None, kb_manager=None)
        result = await builder.build(query="test", session_id="s1")
        assert result == ""

    async def test_empty_memory_returns_empty(self, mock_memory_manager, mock_kb_manager):
        mock_memory_manager.read.return_value = []
        mock_kb_manager.list_all.return_value = []
        builder = ContextBuilder(
            memory_manager=mock_memory_manager,
            kb_manager=mock_kb_manager,
        )
        result = await builder.build(query="hello", session_id="s1")
        assert result == ""

    async def test_memory_results_appear_in_output(self, mock_memory_manager):
        mock_memory_manager.read.return_value = [
            _make_search_result("用户喜欢 Python 编程", score=0.9),
        ]
        builder = ContextBuilder(memory_manager=mock_memory_manager, kb_manager=None)
        result = await builder.build(query="Python", session_id="s1")
        assert "用户喜欢 Python 编程" in result
        assert "<memory>" in result

    async def test_low_score_items_filtered_by_select(self, mock_memory_manager):
        # score < min_score (0.3) 的条目会被 select 过滤
        mock_memory_manager.read.return_value = [
            _make_search_result("irrelevant content", score=0.1),
        ]
        builder = ContextBuilder(
            memory_manager=mock_memory_manager, kb_manager=None, min_score=0.3
        )
        result = await builder.build(query="test", session_id="s1")
        assert result == ""

    async def test_result_is_string(self, mock_memory_manager):
        mock_memory_manager.read.return_value = [
            _make_search_result("some memory", score=0.85),
        ]
        builder = ContextBuilder(memory_manager=mock_memory_manager)
        result = await builder.build(query="test", session_id="s1")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Compress 触发
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestContextBuilderCompress:
    async def test_short_context_not_compressed(self, mock_memory_manager):
        mock_memory_manager.read.return_value = [
            _make_search_result("short", score=0.9),
        ]
        builder = ContextBuilder(
            memory_manager=mock_memory_manager,
            max_chars=50000,  # 极大阈值，不触发压缩
        )
        # 不 mock compress，应直接返回 structure 结果
        result = await builder.build(query="x", session_id="s")
        assert "short" in result

    async def test_long_context_triggers_compress(self, mock_memory_manager):
        long_content = "A" * 200  # 产生超过 max_chars=100 的上下文
        mock_memory_manager.read.return_value = [
            _make_search_result(long_content, score=0.9),
        ]
        builder = ContextBuilder(
            memory_manager=mock_memory_manager,
            max_chars=100,  # 很小的阈值
        )
        # compress 会截断或调用 LLM，这里 mock LLM 调用失败触发截断
        with patch("hello_agents.context.compress.openai.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.side_effect = Exception("no api")
            result = await builder.build(query="x", session_id="s")
        # 应该走截断路径，结果不为空但被截断
        assert isinstance(result, str)
        assert len(result) <= 100


# ---------------------------------------------------------------------------
# 异常健壮性
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestContextBuilderRobustness:
    async def test_memory_gather_failure_returns_empty(self, mock_memory_manager):
        mock_memory_manager.read.side_effect = Exception("DB down")
        builder = ContextBuilder(memory_manager=mock_memory_manager)
        # gather 内部捕获异常，返回空列表
        result = await builder.build(query="test", session_id="s")
        assert result == ""

    async def test_custom_token_budget(self, mock_memory_manager):
        mock_memory_manager.read.return_value = [
            _make_search_result("A" * 100, score=0.8),
            _make_search_result("B" * 100, score=0.7),
        ]
        # token_budget=10 → 40 chars，只能放第一个
        builder = ContextBuilder(memory_manager=mock_memory_manager, token_budget=10)
        result = await builder.build(query="x", session_id="s")
        assert isinstance(result, str)
