"""
UT: memory/types/working.py — WorkingMemory & WorkingMemoryStore
"""

from __future__ import annotations

import time

import pytest

from hello_agents.memory.base import ImportanceLevel, MemoryType
from hello_agents.memory.types.working import WorkingMemory, WorkingMemoryStore


# ---------------------------------------------------------------------------
# WorkingMemory — add / get
# ---------------------------------------------------------------------------

class TestWorkingMemoryAddGet:
    def setup_method(self):
        self.wm = WorkingMemory(session_id="test_session", ttl_seconds=60)

    def test_add_returns_record(self):
        record = self.wm.add("hello world")
        assert record.content == "hello world"
        assert record.memory_type == MemoryType.WORKING
        assert record.source_session_id == "test_session"

    def test_add_with_importance(self):
        record = self.wm.add("critical info", importance=ImportanceLevel.CRITICAL)
        assert record.importance == ImportanceLevel.CRITICAL
        assert record.importance_score == 1.0

    def test_add_with_metadata(self):
        record = self.wm.add("msg", metadata={"role": "user"})
        assert record.metadata["role"] == "user"

    def test_get_existing_record(self):
        record = self.wm.add("existing")
        fetched = self.wm.get(record.id)
        assert fetched is not None
        assert fetched.content == "existing"

    def test_get_nonexistent_returns_none(self):
        assert self.wm.get("nonexistent-id") is None

    def test_get_reinforces_access_count(self):
        record = self.wm.add("reinforce me")
        self.wm.get(record.id)
        updated = self.wm.get(record.id)
        assert updated.access_count >= 1

    def test_len_counts_valid_records(self):
        self.wm.add("a")
        self.wm.add("b")
        assert len(self.wm) == 2


# ---------------------------------------------------------------------------
# TTL / eviction
# ---------------------------------------------------------------------------

class TestTTLEviction:
    def test_expired_record_evicted(self):
        wm = WorkingMemory(session_id="s", ttl_seconds=1)
        record = wm.add("short lived", ttl_override=1)
        assert wm.get(record.id) is not None
        time.sleep(1.1)
        assert wm.get(record.id) is None

    def test_pinned_record_not_expired(self):
        wm = WorkingMemory(session_id="s", ttl_seconds=1)
        record = wm.add("pinned", pinned=True)
        time.sleep(1.1)
        # 即使TTL到了，pinned不会被清除
        result = wm.get_all(include_expired=True)
        ids = [r.id for r in result]
        assert record.id in ids


# ---------------------------------------------------------------------------
# get_all / get_window
# ---------------------------------------------------------------------------

class TestGetAllWindow:
    def setup_method(self):
        self.wm = WorkingMemory(session_id="s", ttl_seconds=3600)

    def test_get_all_returns_all_records(self):
        self.wm.add("a")
        self.wm.add("b")
        self.wm.add("c")
        records = self.wm.get_all()
        assert len(records) == 3

    def test_get_window_last_n(self):
        for i in range(5):
            self.wm.add(f"msg {i}")
        window = self.wm.get_window(last_n=3)
        assert len(window) == 3
        assert window[-1].content == "msg 4"

    def test_get_window_fewer_than_n(self):
        self.wm.add("only one")
        window = self.wm.get_window(last_n=10)
        assert len(window) == 1


# ---------------------------------------------------------------------------
# to_context_string
# ---------------------------------------------------------------------------

class TestToContextString:
    def test_formats_role_content(self):
        wm = WorkingMemory(session_id="s", ttl_seconds=3600)
        wm.add("Hi there", metadata={"role": "user"})
        wm.add("Hello!", metadata={"role": "assistant"})
        ctx = wm.to_context_string(last_n=10)
        assert "[user]: Hi there" in ctx
        assert "[assistant]: Hello!" in ctx

    def test_empty_memory_returns_empty_string(self):
        wm = WorkingMemory(session_id="s", ttl_seconds=3600)
        assert wm.to_context_string() == ""


# ---------------------------------------------------------------------------
# delete / clear
# ---------------------------------------------------------------------------

class TestDeleteClear:
    def setup_method(self):
        self.wm = WorkingMemory(session_id="s", ttl_seconds=3600)

    def test_delete_existing(self):
        record = self.wm.add("to delete")
        assert self.wm.delete(record.id) is True
        assert self.wm.get(record.id) is None

    def test_delete_nonexistent(self):
        assert self.wm.delete("ghost-id") is False

    def test_clear_empties_all(self):
        self.wm.add("a")
        self.wm.add("b")
        self.wm.clear()
        assert len(self.wm) == 0
        assert self.wm.get_all() == []


# ---------------------------------------------------------------------------
# pin / unpin
# ---------------------------------------------------------------------------

class TestPin:
    def test_pin_prevents_trim(self):
        # budget = 5 tokens = 20 chars；pinned 内容 3 chars（在 budget 内）
        wm = WorkingMemory(session_id="s", ttl_seconds=3600, max_tokens=5)
        pinned = wm.add("pin", pinned=True)   # 3 chars，不超过 budget
        # 加入大 filler（100 chars），触发 trim，filler 被移除，pinned 保留
        for _ in range(3):
            wm.add("x" * 100)
        # pinned 记录应还在
        assert pinned.id in {r.id for r in wm.get_all(include_expired=True)}

    def test_unpin(self):
        wm = WorkingMemory(session_id="s", ttl_seconds=3600)
        record = wm.add("pin test", pinned=True)
        wm.unpin(record.id)
        assert record.id not in wm._pinned


# ---------------------------------------------------------------------------
# WorkingMemoryStore
# ---------------------------------------------------------------------------

class TestWorkingMemoryStore:
    def test_get_session_creates_new(self):
        store = WorkingMemoryStore()
        wm = store.get_session("session_1")
        assert isinstance(wm, WorkingMemory)
        assert wm.session_id == "session_1"

    def test_get_session_same_instance(self):
        store = WorkingMemoryStore()
        wm1 = store.get_session("s1")
        wm2 = store.get_session("s1")
        assert wm1 is wm2

    def test_different_sessions_isolated(self):
        store = WorkingMemoryStore()
        store.get_session("s1").add("msg for s1")
        s2 = store.get_session("s2")
        assert len(s2) == 0

    def test_delete_session(self):
        store = WorkingMemoryStore()
        store.get_session("to_delete").add("data")
        store.delete_session("to_delete")
        assert "to_delete" not in store.active_sessions()

    def test_active_sessions(self):
        store = WorkingMemoryStore()
        store.get_session("s1")
        store.get_session("s2")
        sessions = store.active_sessions()
        assert "s1" in sessions
        assert "s2" in sessions
