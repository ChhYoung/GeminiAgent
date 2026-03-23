"""
UT: context/select.py — select() 贪心 Token 裁切
"""

from __future__ import annotations

import pytest

from hello_agents.context.gather import RawItem
from hello_agents.context.select import select


def make_item(content: str, score: float, source: str = "memory") -> RawItem:
    return RawItem(source=source, content=content, score=score)


class TestSelectFiltering:
    def test_filters_below_min_score(self):
        items = [
            make_item("good", score=0.5),
            make_item("too low", score=0.1),
            make_item("just right", score=0.3),
        ]
        result = select(items, token_budget=1000, min_score=0.3)
        contents = [r.content for r in result]
        assert "too low" not in contents
        assert "good" in contents
        assert "just right" in contents

    def test_empty_input_returns_empty(self):
        assert select([], token_budget=1000) == []

    def test_all_below_threshold_returns_empty(self):
        items = [make_item("x", 0.1), make_item("y", 0.2)]
        result = select(items, token_budget=1000, min_score=0.5)
        assert result == []


class TestSelectSorting:
    def test_sorted_by_score_descending(self):
        items = [
            make_item("low", score=0.4),
            make_item("high", score=0.9),
            make_item("mid", score=0.6),
        ]
        result = select(items, token_budget=10000, min_score=0.0)
        assert result[0].content == "high"
        assert result[1].content == "mid"
        assert result[2].content == "low"


class TestSelectTokenBudget:
    def test_respects_token_budget(self):
        # 每个 item 400 chars ≈ 100 tokens；budget = 200 tokens = 800 chars
        items = [make_item("A" * 400, score=0.9), make_item("B" * 400, score=0.8)]
        result = select(items, token_budget=200, min_score=0.0)
        # 两个 item 共 800 chars = 200 token，恰好放得下
        assert len(result) == 2

    def test_truncates_item_that_partially_fits(self):
        # budget 500 tokens = 2000 chars; 第一个 1800 chars，第二个 600 chars（剩 200 chars 可截断）
        items = [
            make_item("A" * 1800, score=0.9),
            make_item("B" * 600, score=0.8),
        ]
        result = select(items, token_budget=500, min_score=0.0)
        assert len(result) == 2
        # 第二个被截断
        assert result[1].metadata.get("truncated") is True
        assert len(result[1].content) < 600

    def test_no_truncation_if_remaining_less_than_100(self):
        # budget = 500 tokens = 2000 chars; 第一个占 1950，剩余 50 < 100，不截断
        items = [
            make_item("A" * 1950, score=0.9),
            make_item("B" * 200, score=0.8),
        ]
        result = select(items, token_budget=500, min_score=0.0)
        assert len(result) == 1
        assert result[0].content == "A" * 1950

    def test_single_item_within_budget(self):
        items = [make_item("short", score=0.9)]
        result = select(items, token_budget=100, min_score=0.0)
        assert len(result) == 1
        assert result[0].content == "short"

    def test_preserves_metadata(self):
        item = RawItem(source="memory", content="data", score=0.8, metadata={"id": "123"})
        result = select([item], token_budget=1000, min_score=0.0)
        assert result[0].metadata["id"] == "123"
