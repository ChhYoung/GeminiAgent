"""
tests/unit/test_compress_layers.py — 三层压缩策略测试

Layer 1: spill_large_results  — 大结果落盘，只留预览
Layer 2: fold_old_results     — 旧结果替换为占位符
Layer 3: summarize_history    — 连续性摘要
向后兼容: sliding_window / llm_summarize / needs_offload / compress
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hello_agents.context.compress import (
    L1_PREVIEW_CHARS,
    L1_RESULT_CHARS,
    L2_KEEP_RECENT,
    compress,
    fold_old_results,
    llm_summarize,
    needs_offload,
    sliding_window,
    spill_large_results,
    summarize_history,
    load_spilled_result,
    apply_all_layers,
)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 1 — spill_large_results
# ──────────────────────────────────────────────────────────────────────────────

class TestSpillLargeResults:
    def _tool_msg(self, content: str, call_id: str = "call_001") -> dict:
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    def test_small_result_unchanged(self):
        msg = self._tool_msg("short result")
        result = spill_large_results([msg])
        assert result[0]["content"] == "short result"

    def test_large_result_spilled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hello_agents.context.compress._SPILL_DIR", tmp_path / "spill"
        )
        big_content = "X" * (L1_RESULT_CHARS + 100)
        msg = self._tool_msg(big_content, call_id="call_big")
        result = spill_large_results([msg])
        content = result[0]["content"]
        assert "落盘" in content or "spill" in content.lower() or "预览" in content
        assert len(content) < len(big_content)

    def test_non_tool_messages_unchanged(self):
        msgs = [
            {"role": "user", "content": "X" * 5000},
            {"role": "assistant", "content": "Y" * 5000},
        ]
        result = spill_large_results(msgs)
        assert result[0]["content"] == msgs[0]["content"]
        assert result[1]["content"] == msgs[1]["content"]

    def test_spill_file_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hello_agents.context.compress._SPILL_DIR", tmp_path / "spill"
        )
        big = "Z" * (L1_RESULT_CHARS + 1)
        spill_large_results([self._tool_msg(big, call_id="test_spill")])
        spill_file = tmp_path / "spill" / "test_spill.txt"
        assert spill_file.exists()
        assert spill_file.read_text() == big

    def test_load_spilled_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hello_agents.context.compress._SPILL_DIR", tmp_path / "spill"
        )
        big = "A" * (L1_RESULT_CHARS + 1)
        spill_large_results([self._tool_msg(big, call_id="recover_me")])
        recovered = load_spilled_result("recover_me")
        assert recovered is not None
        assert len(recovered) == len(big)

    def test_load_nonexistent_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hello_agents.context.compress._SPILL_DIR", tmp_path / "spill"
        )
        assert load_spilled_result("ghost_call") is None

    def test_json_result_preview(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "hello_agents.context.compress._SPILL_DIR", tmp_path / "spill"
        )
        import json
        data = {f"key{i}": f"value{i}" * 10 for i in range(20)}
        big = json.dumps(data)
        # Make it big enough to spill
        big = big + "X" * max(0, L1_RESULT_CHARS + 10 - len(big))
        msg = self._tool_msg(big, call_id="json_call")
        result = spill_large_results([msg])
        # Preview should be there (either key listing or truncation)
        assert len(result[0]["content"]) < len(big)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 — fold_old_results
# ──────────────────────────────────────────────────────────────────────────────

class TestFoldOldResults:
    def _msgs(self, n_tool: int) -> list[dict]:
        """Build a simple alternating user/assistant/tool sequence."""
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n_tool):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"call_{i}", "function": {"name": f"tool_{i}", "arguments": "{}"}}],
            })
            msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": f"result {i}"})
        return msgs

    def test_few_results_unchanged(self):
        msgs = self._msgs(3)
        result = fold_old_results(msgs, keep_recent=6)
        tool_contents = [m["content"] for m in result if m.get("role") == "tool"]
        assert all("折叠" not in c for c in tool_contents)

    def test_old_results_folded(self):
        msgs = self._msgs(10)
        result = fold_old_results(msgs, keep_recent=3)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        folded = [m for m in tool_msgs if "折叠" in m["content"]]
        kept = [m for m in tool_msgs if "折叠" not in m["content"]]
        assert len(kept) == 3
        assert len(folded) == 7

    def test_non_tool_messages_untouched(self):
        msgs = self._msgs(5)
        result = fold_old_results(msgs, keep_recent=2)
        user_contents = [m["content"] for m in result if m.get("role") == "user"]
        assert all(c.startswith("q") for c in user_contents)

    def test_exactly_keep_recent(self):
        msgs = self._msgs(4)
        result = fold_old_results(msgs, keep_recent=4)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        folded = [m for m in tool_msgs if "折叠" in m["content"]]
        assert len(folded) == 0

    def test_empty_messages(self):
        assert fold_old_results([], keep_recent=3) == []

    def test_no_tool_messages(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = fold_old_results(msgs)
        assert result == msgs


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 — summarize_history
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_history_below_threshold():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = await summarize_history(msgs, max_total_chars=100000)
    assert result == msgs  # unchanged


@pytest.mark.asyncio
async def test_summarize_history_above_threshold():
    # Build messages that exceed threshold
    msgs = [{"role": "system", "content": "You are an agent."}]
    for i in range(30):
        msgs.append({"role": "user", "content": f"question {i}: " + "X" * 200})
        msgs.append({"role": "assistant", "content": f"answer {i}: " + "Y" * 200})

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "历史摘要内容"

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        result = await summarize_history(msgs, keep_recent=2, max_total_chars=1000)

    # System message should still be first
    assert result[0]["role"] == "system"
    # Should have fewer messages than original
    assert len(result) < len(msgs)
    # Should contain summary message
    summary_msgs = [m for m in result if "摘要" in m.get("content", "")]
    assert len(summary_msgs) >= 1


@pytest.mark.asyncio
async def test_summarize_history_preserves_recent():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(20):
        msgs.append({"role": "user", "content": "q" * 300})
        msgs.append({"role": "assistant", "content": "a" * 300})

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "摘要"

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        result = await summarize_history(msgs, keep_recent=3, max_total_chars=1000)

    # Last 3*2=6 messages should be preserved (plus system and summary)
    tail = [m for m in result if m.get("role") in ("user", "assistant")]
    assert len(tail) <= 6


# ──────────────────────────────────────────────────────────────────────────────
# apply_all_layers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_all_layers_no_op_small(tmp_path, monkeypatch):
    monkeypatch.setattr("hello_agents.context.compress._SPILL_DIR", tmp_path / "s")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "c1", "content": "small"},
    ]
    result = await apply_all_layers(msgs, history_threshold=100000)
    assert len(result) == 3


# ──────────────────────────────────────────────────────────────────────────────
# 向后兼容接口（v4 tests, unchanged）
# ──────────────────────────────────────────────────────────────────────────────

class TestSlidingWindow:
    def test_no_truncation_when_within_limit(self):
        items = list(range(10))
        assert sliding_window(items, max_items=10) == items

    def test_truncates_to_max_items(self):
        items = list(range(30))
        assert len(sliding_window(items, max_items=10)) == 10

    def test_keeps_most_recent(self):
        items = list(range(20))
        assert sliding_window(items, max_items=5)[-1] == 19

    def test_keep_first_preserved(self):
        items = list(range(20))
        result = sliding_window(items, max_items=5, keep_first=2)
        assert result[0] == 0 and result[1] == 1
        assert len(result) == 5

    def test_empty_list(self):
        assert sliding_window([], max_items=10) == []

    def test_single_item(self):
        assert sliding_window([42], max_items=5) == [42]

    def test_exact_max_items(self):
        items = list(range(5))
        assert sliding_window(items, max_items=5) == items


@pytest.mark.asyncio
async def test_llm_summarize_no_op_when_short():
    assert await llm_summarize("short", max_chars=1000) == "short"


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


@pytest.mark.asyncio
async def test_llm_summarize_fallback_on_error():
    long_ctx = "x" * 5000
    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_cls.return_value = mock_client
        result = await llm_summarize(long_ctx, max_chars=1000)
    assert len(result) == 1000


class TestNeedsOffload:
    def test_below_threshold(self):
        assert needs_offload("short", offload_chars=100) is False

    def test_above_threshold(self):
        assert needs_offload("x" * 200, offload_chars=100) is True

    def test_exactly_threshold(self):
        assert needs_offload("x" * 100, offload_chars=100) is False


@pytest.mark.asyncio
async def test_compress_no_op_when_short():
    assert await compress("short", max_chars=1000) == "short"


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
