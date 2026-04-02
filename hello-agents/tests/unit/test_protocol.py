"""
tests/unit/test_protocol.py — AgentMessage 协议测试 (s10)
"""

from __future__ import annotations

import pytest

from hello_agents.multi_agent.protocol import AgentMessage


class TestAgentMessage:
    def test_defaults(self):
        msg = AgentMessage(
            from_agent="a",
            to_agent="b",
            payload={"content": "hello"},
        )
        assert msg.msg_type == "request"
        assert msg.correlation_id is None
        assert len(msg.msg_id) > 0

    def test_unique_msg_ids(self):
        ids = {AgentMessage(from_agent="a", to_agent="b", payload={}).msg_id for _ in range(10)}
        assert len(ids) == 10

    def test_to_dict_contains_required_fields(self):
        msg = AgentMessage(from_agent="a", to_agent="b", payload={"k": "v"})
        d = msg.to_dict()
        for field in ("msg_id", "msg_type", "from_agent", "to_agent", "payload", "created_at"):
            assert field in d

    def test_from_dict_roundtrip(self):
        msg = AgentMessage(
            from_agent="agent-1",
            to_agent="agent-2",
            msg_type="response",
            correlation_id="req-001",
            payload={"result": "done"},
        )
        d = msg.to_dict()
        msg2 = AgentMessage.from_dict(d)
        assert msg2.msg_id == msg.msg_id
        assert msg2.msg_type == "response"
        assert msg2.from_agent == "agent-1"
        assert msg2.correlation_id == "req-001"
        assert msg2.payload == {"result": "done"}

    def test_make_response(self):
        req = AgentMessage(
            from_agent="main",
            to_agent="worker",
            payload={"content": "请执行任务"},
        )
        resp = req.make_response(from_agent="worker", payload={"result": "完成"})
        assert resp.msg_type == "response"
        assert resp.from_agent == "worker"
        assert resp.to_agent == "main"
        assert resp.correlation_id == req.msg_id

    def test_from_dict_missing_created_at(self):
        d = {
            "msg_id": "x1",
            "msg_type": "event",
            "from_agent": "a",
            "to_agent": "b",
            "payload": {},
        }
        msg = AgentMessage.from_dict(d)
        assert msg.msg_id == "x1"

    def test_event_type(self):
        msg = AgentMessage(
            from_agent="sys",
            to_agent="all",
            msg_type="event",
            payload={"event": "task_done"},
        )
        assert msg.msg_type == "event"
