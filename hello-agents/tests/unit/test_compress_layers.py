"""
tests/unit/test_compress_layers.py — 三层压缩策略测试 (s06)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.context.compress import (
    compress,
    llm_summarize,
    needs_offload,
    sliding_window,
)


# ---------------------------------------------------------------------------
# Layer 1 — sliding_window
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_no_truncation_when_within_limit(self):
        items = list(range(10))
        result = sliding_window(items, max_items=10)
        assert result == items

    def test_truncates_to_max_items(self):
        items = list(range(30))
        result = sliding_window(items, max_items=10)
        assert len(result) == 10

    def test_keeps_most_recent(self):
        items = list(range(20))
        result = sliding_window(items, max_items=5)
        assert result[-1] == 19  # 最新的保留

    def test_keep_first_preserved(self):
        items = list(range(20))
        result = sliding_window(items, max_items=5, keep_first=2)
        assert result[0] == 0
        assert result[1] == 1
        assert len(result) == 5

    def test_empty_list(self):
        assert sliding_window([], max_items=10) == []

    def test_single_item(self):
        assert sliding_window([42], max_items=5) == [42]

    def test_exact_max_items(self):
        items = list(range(5))
        assert sliding_window(items, max_items=5) == items


# ---------------------------------------------------------------------------
# Layer 2 — llm_summarize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_summarize_no_op_when_short():
    short_ctx = "short context"
    result = await llm_summarize(short_ctx, max_chars=1000)
    assert result == short_ctx


@pytest.mark.asyncio
async def test_llm_summarize_calls_llm_when_long():
    long_ctx = "x" * 15000
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "摘要内容"

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        result = await llm_summarize(long_ctx, max_chars=1000)
        assert result == "摘要内容"
        mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_llm_summarize_fallback_on_error():
    long_ctx = "x" * 5000
    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_cls.return_value = mock_client

        result = await llm_summarize(long_ctx, max_chars=1000)
        # 降级为截断
        assert len(result) == 1000
        assert result == long_ctx[:1000]


# ---------------------------------------------------------------------------
# Layer 3 — needs_offload
# ---------------------------------------------------------------------------

class TestNeedsOffload:
    def test_below_threshold(self):
        assert needs_offload("short", offload_chars=100) is False

    def test_above_threshold(self):
        assert needs_offload("x" * 200, offload_chars=100) is True

    def test_exactly_threshold(self):
        # 等于阈值时不触发（严格大于）
        ctx = "x" * 100
        assert needs_offload(ctx, offload_chars=100) is False


# ---------------------------------------------------------------------------
# compress() — 向后兼容入口
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compress_no_op_when_short():
    ctx = "short"
    result = await compress(ctx, max_chars=1000)
    assert result == ctx


@pytest.mark.asyncio
async def test_compress_delegates_to_llm_summarize():
    long_ctx = "y" * 5000
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "compressed"

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        result = await compress(long_ctx, max_chars=100)
        assert result == "compressed"
