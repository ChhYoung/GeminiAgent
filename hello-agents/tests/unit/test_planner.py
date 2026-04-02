"""
tests/unit/test_planner.py — Planner 单元测试 (s03)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hello_agents.planner.planner import Planner, Step


# ---------------------------------------------------------------------------
# _parse_steps
# ---------------------------------------------------------------------------

class TestParseSteps:
    def setup_method(self):
        self.planner = Planner.__new__(Planner)  # 跳过 __init__ 中的 LLM 初始化

    def test_valid_json_array(self):
        raw = json.dumps([
            {"id": "1", "desc": "搜索资料", "tool_hint": "web_search", "deps": []},
            {"id": "2", "desc": "整理笔记", "tool_hint": "create_note", "deps": ["1"]},
        ])
        steps = self.planner._parse_steps(raw)
        assert len(steps) == 2
        assert steps[0].id == "1"
        assert steps[0].desc == "搜索资料"
        assert steps[0].tool_hint == "web_search"
        assert steps[1].deps == ["1"]

    def test_json_embedded_in_text(self):
        raw = 'Here are the steps:\n[{"id":"1","desc":"step one","deps":[]}]\nDone.'
        steps = self.planner._parse_steps(raw)
        assert len(steps) == 1
        assert steps[0].desc == "step one"

    def test_missing_optional_fields(self):
        raw = json.dumps([{"id": "1", "desc": "do something"}])
        steps = self.planner._parse_steps(raw)
        assert steps[0].tool_hint == ""
        assert steps[0].deps == []

    def test_invalid_json_returns_fallback(self):
        raw = "这不是 JSON"
        steps = self.planner._parse_steps(raw)
        assert len(steps) == 1
        assert steps[0].id == "1"
        assert "这不是 JSON" in steps[0].desc

    def test_empty_array_returns_fallback(self):
        raw = "[]"
        steps = self.planner._parse_steps(raw)
        assert len(steps) == 1

    def test_no_bracket_returns_fallback(self):
        steps = self.planner._parse_steps("no brackets here")
        assert len(steps) == 1

    def test_numeric_id_converted_to_str(self):
        raw = json.dumps([{"id": 1, "desc": "step", "deps": []}])
        steps = self.planner._parse_steps(raw)
        assert isinstance(steps[0].id, str)

    def test_dep_ids_converted_to_str(self):
        raw = json.dumps([{"id": "2", "desc": "step", "deps": [1]}])
        steps = self.planner._parse_steps(raw)
        assert steps[0].deps == ["1"]


# ---------------------------------------------------------------------------
# steps_to_prompt
# ---------------------------------------------------------------------------

class TestStepsToPrompt:
    def test_basic_prompt(self):
        steps = [
            Step(id="1", desc="搜索资料", tool_hint="web_search", deps=[]),
            Step(id="2", desc="整理结果", deps=["1"]),
        ]
        prompt = Planner.steps_to_prompt(steps)
        assert "当前任务计划" in prompt
        assert "[1]" in prompt
        assert "搜索资料" in prompt
        assert "[web_search]" in prompt
        assert "依赖：1" in prompt

    def test_no_tool_hint(self):
        steps = [Step(id="1", desc="执行任务")]
        prompt = Planner.steps_to_prompt(steps)
        assert "[" not in prompt.split("[1]")[1].split("\n")[0]  # 无方括号工具名


# ---------------------------------------------------------------------------
# make_plan (mock LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_plan_success():
    planner = Planner.__new__(Planner)
    planner._model = "test-model"

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps([
        {"id": "1", "desc": "收集数据", "deps": []},
        {"id": "2", "desc": "分析数据", "deps": ["1"]},
    ])

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    planner._client = mock_client

    steps = await planner.make_plan("分析销售数据")
    assert len(steps) == 2
    assert steps[1].deps == ["1"]


@pytest.mark.asyncio
async def test_make_plan_fallback_on_error():
    planner = Planner.__new__(Planner)
    planner._model = "test-model"

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")
    planner._client = mock_client

    steps = await planner.make_plan("某个目标")
    assert len(steps) == 1
    assert "某个目标" in steps[0].desc
