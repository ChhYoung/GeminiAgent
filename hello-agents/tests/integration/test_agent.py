"""
集成测试: agent.py — HelloAgent 多轮对话与 Function Calling
mock 替代 OpenAI 客户端和记忆系统，不依赖真实 API。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.agent import HelloAgent
from hello_agents.memory.base import ImportanceLevel, MemoryType
from hello_agents.memory.types.working import WorkingMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_completion(content: str, tool_calls=None):
    """构造 mock OpenAI ChatCompletion 响应。"""
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def mock_memory_manager():
    mm = MagicMock()
    wm = WorkingMemory(session_id="default")
    mm.get_working_memory.return_value = wm
    mm.read.return_value = []
    mm.write = MagicMock()
    mm.start = AsyncMock()
    mm.stop = AsyncMock()
    return mm


@pytest.fixture
def mock_kb_manager():
    kb = MagicMock()
    kb.list_all.return_value = []
    return kb


@pytest.fixture
def agent(mock_memory_manager, mock_kb_manager):
    with patch("hello_agents.agent.openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        a = HelloAgent(
            memory_manager=mock_memory_manager,
            kb_manager=mock_kb_manager,
        )
        a._client = mock_client
        return a


# ---------------------------------------------------------------------------
# start / stop 生命周期
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAgentLifecycle:
    async def test_start_calls_memory_start(self, agent, mock_memory_manager):
        await agent.start()
        mock_memory_manager.start.assert_called_once()

    async def test_stop_calls_memory_stop(self, agent, mock_memory_manager):
        await agent.stop()
        mock_memory_manager.stop.assert_called_once()


# ---------------------------------------------------------------------------
# chat() — 普通文本响应
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAgentChat:
    async def test_chat_returns_assistant_response(self, agent):
        agent._client.chat.completions.create.return_value = _make_completion("你好，我是助手！")
        response = await agent.chat("你好", session_id="test")
        assert response == "你好，我是助手！"

    async def test_chat_adds_to_working_memory(self, agent, mock_memory_manager):
        agent._client.chat.completions.create.return_value = _make_completion("OK")
        await agent.chat("test message", session_id="session1")
        wm = mock_memory_manager.get_working_memory("session1")
        records = wm.get_all()
        contents = [r.content for r in records]
        assert "test message" in contents
        assert "OK" in contents

    async def test_chat_empty_response_returns_empty_string(self, agent):
        agent._client.chat.completions.create.return_value = _make_completion("")
        response = await agent.chat("hi", session_id="s")
        assert response == ""

    async def test_chat_calls_context_builder(self, agent):
        with patch.object(agent._ctx_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "some context"
            agent._client.chat.completions.create.return_value = _make_completion("response")
            await agent.chat("query", session_id="s", include_context=True)
            mock_build.assert_called_once()

    async def test_chat_skips_context_when_disabled(self, agent):
        with patch.object(agent._ctx_builder, "build", new_callable=AsyncMock) as mock_build:
            agent._client.chat.completions.create.return_value = _make_completion("response")
            await agent.chat("query", session_id="s", include_context=False)
            mock_build.assert_not_called()

    async def test_context_builder_failure_doesnt_crash(self, agent):
        with patch.object(agent._ctx_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_build.side_effect = Exception("context failed")
            agent._client.chat.completions.create.return_value = _make_completion("still works")
            response = await agent.chat("test", session_id="s", include_context=True)
            assert response == "still works"


# ---------------------------------------------------------------------------
# Function Calling — 工具调用流程
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAgentFunctionCalling:
    async def test_tool_call_dispatched(self, agent):
        # 第一轮：LLM 返回 tool_call
        tool_call = MagicMock()
        tool_call.id = "call_001"
        tool_call.function.name = "create_note"
        tool_call.function.arguments = '{"title": "T", "content": "C"}'

        first_response = _make_completion(None, tool_calls=[tool_call])
        # model_dump() 返回可序列化的字典
        first_response.choices[0].message.model_dump.return_value = {
            "role": "assistant", "content": None, "tool_calls": []
        }

        # 第二轮：正常文本响应
        second_response = _make_completion("笔记已创建！")

        agent._client.chat.completions.create.side_effect = [first_response, second_response]

        # mock registry dispatch
        with patch.object(agent._registry, "dispatch", return_value='{"status":"created","note_id":1}') as mock_dispatch:
            response = await agent.chat("记录一个笔记", session_id="s")
            mock_dispatch.assert_called_once()
        assert response == "笔记已创建！"

    async def test_max_tool_rounds_stops_loop(self, agent):
        """超过最大工具轮次（5）后返回最后的 content。"""
        tool_call = MagicMock()
        tool_call.id = "call_001"
        tool_call.function.name = "some_tool"
        tool_call.function.arguments = "{}"

        looping_response = _make_completion(None, tool_calls=[tool_call])
        looping_response.choices[0].message.model_dump.return_value = {
            "role": "assistant", "content": "final", "tool_calls": []
        }
        looping_response.choices[0].message.content = "final"

        agent._client.chat.completions.create.return_value = looping_response
        with patch.object(agent._registry, "dispatch", return_value='{"ok":true}'):
            response = await agent.chat("keep calling tools", session_id="s")
        # 应该在 5 轮后停止，不无限循环
        assert isinstance(response, str)
        assert agent._client.chat.completions.create.call_count <= 5


# ---------------------------------------------------------------------------
# add_knowledge 便捷接口
# ---------------------------------------------------------------------------

class TestAgentAddKnowledge:
    def test_add_knowledge_text(self, agent, mock_kb_manager):
        mock_kb = MagicMock()
        mock_kb_manager.create.return_value = mock_kb

        agent.add_knowledge("my_kb", text="Some knowledge text")

        mock_kb_manager.create.assert_called_once_with("my_kb", description="")
        mock_kb.add_text.assert_called_once_with("Some knowledge text")

    def test_add_knowledge_file(self, agent, mock_kb_manager):
        mock_kb = MagicMock()
        mock_kb_manager.create.return_value = mock_kb

        agent.add_knowledge("my_kb", file_path="/path/to/doc.pdf")
        mock_kb.add_file.assert_called_once_with("/path/to/doc.pdf")
