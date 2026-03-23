"""
UT: context/structure.py — structure() XML 格式化
"""

from __future__ import annotations

import pytest

from hello_agents.context.gather import RawItem
from hello_agents.context.structure import structure


def make_item(source: str, content: str, score: float = 0.8, **meta) -> RawItem:
    return RawItem(source=source, content=content, score=score, metadata=meta)


class TestStructureEmpty:
    def test_empty_input_returns_empty_string(self):
        assert structure([]) == ""


class TestStructureMemoryGroup:
    def test_memory_items_wrapped_in_tags(self):
        items = [make_item("memory", "用户喜欢 Python", score=0.85)]
        result = structure(items)
        assert "<memory>" in result
        assert "</memory>" in result
        assert "用户喜欢 Python" in result

    def test_memory_shows_score(self):
        items = [make_item("memory", "content", score=0.75)]
        result = structure(items)
        assert "score=0.75" in result

    def test_memory_multiple_items_numbered(self):
        items = [
            make_item("memory", "first", score=0.9),
            make_item("memory", "second", score=0.8),
        ]
        result = structure(items)
        assert "[1]" in result
        assert "[2]" in result


class TestStructureRAGGroup:
    def test_rag_items_wrapped_in_knowledge_tags(self):
        items = [make_item("rag", "Some document content", source_file="doc.pdf", section="3")]
        result = structure(items)
        assert "<knowledge>" in result
        assert "</knowledge>" in result
        assert "doc.pdf" in result

    def test_rag_shows_source_and_section(self):
        items = [make_item("rag", "chunk text", source_file="manual.pdf", section="2.1")]
        result = structure(items)
        assert "manual.pdf" in result
        assert "2.1" in result

    def test_rag_unknown_source_uses_unknown(self):
        items = [RawItem(source="rag", content="no meta", score=0.7)]
        result = structure(items)
        assert "unknown" in result


class TestStructureSystemStateGroup:
    def test_system_state_wrapped_in_tags(self):
        items = [make_item("system_state", "CPU: 20%")]
        result = structure(items)
        assert "<system_state>" in result
        assert "CPU: 20%" in result


class TestStructureMixedGroups:
    def test_multiple_groups_all_present(self):
        items = [
            make_item("memory", "mem content", score=0.8),
            make_item("rag", "rag content", source_file="f.pdf", section="1"),
            make_item("system_state", "sys info"),
        ]
        result = structure(items)
        assert "<memory>" in result
        assert "<knowledge>" in result
        assert "<system_state>" in result

    def test_unknown_source_ignored(self):
        items = [make_item("custom_source", "custom data")]
        result = structure(items)
        # 未知 source 不产生任何 XML 块
        assert result == ""

    def test_groups_separated_by_double_newline(self):
        items = [
            make_item("memory", "m1", score=0.9),
            make_item("rag", "r1", source_file="f.pdf", section="1"),
        ]
        result = structure(items)
        assert "\n\n" in result
