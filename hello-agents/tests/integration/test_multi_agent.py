"""
tests/integration/test_multi_agent.py — 多 Agent 协作测试 (s09/s10/s11)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.peer import PeerAgent
from hello_agents.multi_agent.protocol import AgentMessage
from hello_agents.multi_agent.registry import AgentRegistry
from hello_agents.tools.builtin.agent_tool import AgentToolHandler


# ---------------------------------------------------------------------------
# PeerAgent
# ---------------------------------------------------------------------------

class TestPeerAgent:
    def test_to_dict_roundtrip(self):
        a = PeerAgent(
            agent_id="w1",
            name="Worker-1",
            speciality="代码审查",
            system_prompt="You are a reviewer",
            tool_names=["run_command"],
        )
        d = a.to_dict()
        a2 = PeerAgent.from_dict(d)
        assert a2.agent_id == "w1"
        assert a2.speciality == "代码审查"
        assert a2.tool_names == ["run_command"]


# ---------------------------------------------------------------------------
# Mailbox (sync API)
# ---------------------------------------------------------------------------

class TestMailbox:
    def _mailbox(self, tmp_path: Path) -> Mailbox:
        return Mailbox(db_path=tmp_path / "test_mailbox.db")

    def test_send_recv_sync(self, tmp_path):
        mb = self._mailbox(tmp_path)
        msg = AgentMessage(from_agent="a", to_agent="b", payload={"content": "hello"})
        mb.send_sync("b", msg)
        received = mb.recv_sync("b")
        assert received is not None
        assert received.msg_id == msg.msg_id
        assert received.payload["content"] == "hello"

    def test_recv_returns_none_when_empty(self, tmp_path):
        mb = self._mailbox(tmp_path)
        assert mb.recv_sync("nobody") is None

    def test_message_consumed_after_recv(self, tmp_path):
        mb = self._mailbox(tmp_path)
        msg = AgentMessage(from_agent="a", to_agent="b", payload={})
        mb.send_sync("b", msg)
        mb.recv_sync("b")
        assert mb.recv_sync("b") is None

    def test_pending_count(self, tmp_path):
        mb = self._mailbox(tmp_path)
        assert mb.pending_count("x") == 0
        mb.send_sync("x", AgentMessage(from_agent="a", to_agent="x", payload={}))
        assert mb.pending_count("x") == 1

    def test_fifo_order(self, tmp_path):
        mb = self._mailbox(tmp_path)
        for i in range(3):
            mb.send_sync("c", AgentMessage(from_agent="a", to_agent="c", payload={"i": i}))
        for expected_i in range(3):
            msg = mb.recv_sync("c")
            assert msg.payload["i"] == expected_i

    def test_different_agents_isolated(self, tmp_path):
        mb = self._mailbox(tmp_path)
        mb.send_sync("a", AgentMessage(from_agent="x", to_agent="a", payload={"for": "a"}))
        mb.send_sync("b", AgentMessage(from_agent="x", to_agent="b", payload={"for": "b"}))
        msg_a = mb.recv_sync("a")
        msg_b = mb.recv_sync("b")
        assert msg_a.payload["for"] == "a"
        assert msg_b.payload["for"] == "b"


# ---------------------------------------------------------------------------
# Mailbox (async API)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mailbox_async_send_recv(tmp_path):
    mb = Mailbox(db_path=tmp_path / "async_test.db")
    msg = AgentMessage(from_agent="p", to_agent="q", payload={"data": 42})
    await mb.send("q", msg)
    received = await mb.recv("q")
    assert received is not None
    assert received.payload["data"] == 42


@pytest.mark.asyncio
async def test_mailbox_async_recv_returns_none_when_empty(tmp_path):
    mb = Mailbox(db_path=tmp_path / "empty_test.db")
    result = await mb.recv("nobody")
    assert result is None


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    def test_register_and_get(self):
        r = AgentRegistry()
        a = PeerAgent("a1", "Alice", "research", "You are a researcher")
        r.register(a)
        assert r.get("a1") is a

    def test_get_unknown(self):
        r = AgentRegistry()
        assert r.get("nope") is None

    def test_list_agents(self):
        r = AgentRegistry()
        r.register(PeerAgent("a", "A", "x", ""))
        r.register(PeerAgent("b", "B", "y", ""))
        assert len(r.list_agents()) == 2

    def test_unregister(self):
        r = AgentRegistry()
        r.register(PeerAgent("a", "A", "x", ""))
        assert r.unregister("a") is True
        assert r.get("a") is None
        assert r.unregister("a") is False


# ---------------------------------------------------------------------------
# AgentToolHandler
# ---------------------------------------------------------------------------

class TestAgentToolHandler:
    def _handler(self, tmp_path: Path) -> AgentToolHandler:
        mb = Mailbox(db_path=tmp_path / "handler.db")
        return AgentToolHandler(from_agent_id="main", mailbox=mb)

    def _tc(self, name: str, args: dict) -> MagicMock:
        tc = MagicMock()
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    def test_send_to_agent(self, tmp_path):
        handler = self._handler(tmp_path)
        tc = self._tc("send_to_agent", {"to_agent": "worker", "content": "请执行任务"})
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "sent"
        assert result["to"] == "worker"

    def test_read_mailbox_empty(self, tmp_path):
        handler = self._handler(tmp_path)
        tc = self._tc("read_mailbox", {"agent_id": "main"})
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "empty"

    def test_send_then_read(self, tmp_path):
        mb = Mailbox(db_path=tmp_path / "srtest.db")
        handler = AgentToolHandler(from_agent_id="sender", mailbox=mb)

        # sender 发给 receiver
        tc_send = self._tc("send_to_agent", {"to_agent": "receiver", "content": "任务内容"})
        handler.dispatch(tc_send)

        # receiver 读邮箱
        handler2 = AgentToolHandler(from_agent_id="receiver", mailbox=mb)
        tc_read = self._tc("read_mailbox", {"agent_id": "receiver"})
        result = json.loads(handler2.dispatch(tc_read))
        assert result["status"] == "received"
        assert result["message"]["payload"]["content"] == "任务内容"

    def test_list_agents_empty(self, tmp_path):
        handler = self._handler(tmp_path)
        tc = self._tc("list_agents", {})
        result = json.loads(handler.dispatch(tc))
        assert "agents" in result

    def test_invalid_json(self, tmp_path):
        handler = self._handler(tmp_path)
        tc = MagicMock()
        tc.function.name = "send_to_agent"
        tc.function.arguments = "invalid json"
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
