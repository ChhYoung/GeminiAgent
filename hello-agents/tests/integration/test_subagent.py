"""
tests/integration/test_subagent.py — SubAgentRunner 上下文隔离测试 (s04)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hello_agents.subagent.runner import SubAgentRunner


def _make_text_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = text
    resp.choices[0].message.tool_calls = None
    return resp


def _make_tool_response(tool_name: str, args: str, call_id: str = "c1") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = args

    resp = MagicMock()
    resp.choices[0].message.content = None
    resp.choices[0].message.tool_calls = [tc]
    resp.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "function": {"name": tool_name, "arguments": args}}],
    }
    return resp


@pytest.mark.asyncio
async def test_run_returns_text():
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 5
    runner._registry = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_text_response("子任务完成")
    runner._client = mock_client

    result = await runner.run("执行某个子任务")
    assert result == "子任务完成"


@pytest.mark.asyncio
async def test_run_isolated_context():
    """验证 SubAgentRunner 使用独立 messages[]，不包含外部历史。"""
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 5
    runner._registry = None

    captured_messages = []

    def fake_create(**kwargs):
        captured_messages.append(kwargs["messages"])
        return _make_text_response("done")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create
    runner._client = mock_client

    await runner.run("子任务描述", context_hint="背景信息")

    assert len(captured_messages) == 1
    msgs = captured_messages[0]
    # 只有 system + user，没有外部对话历史
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert len(msgs) == 2
    assert "背景信息" in msgs[0]["content"]


@pytest.mark.asyncio
async def test_run_with_tool_call():
    """验证 SubAgentRunner 能处理一轮 tool_call。"""
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 5

    mock_registry = MagicMock()
    mock_registry.get_schemas.return_value = [{"type": "function", "function": {"name": "test_tool"}}]
    mock_registry.dispatch.return_value = '{"result": "tool_result"}'
    runner._registry = mock_registry

    tool_resp = _make_tool_response("test_tool", '{"key": "val"}')
    text_resp = _make_text_response("最终回复")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [tool_resp, text_resp]
    runner._client = mock_client

    result = await runner.run("执行有工具的任务")
    assert result == "最终回复"
    mock_registry.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_not_polluted_between_calls():
    """两次独立调用的 messages 互不影响。"""
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 5
    runner._registry = None

    all_messages = []

    def fake_create(**kwargs):
        all_messages.append(list(kwargs["messages"]))
        return _make_text_response("ok")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create
    runner._client = mock_client

    await runner.run("任务A")
    await runner.run("任务B")

    assert len(all_messages) == 2
    # 两次调用的 user 消息不同
    assert all_messages[0][1]["content"] == "任务A"
    assert all_messages[1][1]["content"] == "任务B"
    # 第二次调用的 messages 不含第一次的消息
    assert len(all_messages[1]) == 2


@pytest.mark.asyncio
async def test_run_max_tool_rounds_stops_loop():
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 2
    runner._registry = MagicMock()
    runner._registry.get_schemas.return_value = []
    runner._registry.dispatch.return_value = "{}"

    # 每次都返回 tool_call，永不返回文本
    tool_resp = _make_tool_response("some_tool", "{}")
    tool_resp.choices[0].message.model_dump.return_value = {"role": "assistant", "content": None, "tool_calls": []}

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = tool_resp
    runner._client = mock_client

    result = await runner.run("永不结束的任务")
    # 超过 max_rounds 后返回 content（可能为 None → ""）
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_run_empty_response_returns_empty_string():
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner._model = "test-model"
    runner._max_tool_rounds = 5
    runner._registry = None

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    runner._client = mock_client

    result = await runner.run("空响应任务")
    assert result == ""
