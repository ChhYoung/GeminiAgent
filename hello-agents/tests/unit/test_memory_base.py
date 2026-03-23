"""
UT: memory/base.py — MemoryRecord 遗忘曲线与序列化
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from hello_agents.memory.base import (
    ImportanceLevel,
    MemoryQuery,
    MemoryRecord,
    MemoryType,
)


# ---------------------------------------------------------------------------
# 创建与默认值
# ---------------------------------------------------------------------------

class TestMemoryRecordCreation:
    def test_defaults(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="hello")
        assert r.strength == 1.0
        assert r.stability == 1.0
        assert r.access_count == 0
        assert r.importance == ImportanceLevel.MEDIUM
        assert r.memory_type == MemoryType.EPISODIC
        assert r.content == "hello"
        assert r.id  # UUID 非空

    def test_strength_clamped_above_1(self):
        r = MemoryRecord(memory_type=MemoryType.WORKING, content="x", strength=1.5)
        assert r.strength == 1.0

    def test_strength_clamped_below_0(self):
        r = MemoryRecord(memory_type=MemoryType.WORKING, content="x", strength=-0.5)
        assert r.strength == 0.0

    def test_unique_ids(self):
        r1 = MemoryRecord(memory_type=MemoryType.WORKING, content="a")
        r2 = MemoryRecord(memory_type=MemoryType.WORKING, content="b")
        assert r1.id != r2.id


# ---------------------------------------------------------------------------
# decay()
# ---------------------------------------------------------------------------

class TestDecay:
    def test_no_elapsed_strength_stays_1(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="x")
        now = r.last_accessed
        strength = r.decay(now=now)
        assert math.isclose(strength, 1.0, abs_tol=1e-6)

    def test_one_day_elapsed(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="x", stability=1.0)
        one_day_later = r.last_accessed + timedelta(days=1)
        strength = r.decay(now=one_day_later)
        # e^(-1/1) ≈ 0.368
        expected = math.exp(-1.0)
        assert math.isclose(strength, expected, rel_tol=1e-5)

    def test_decay_sets_record_strength(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="x", stability=1.0)
        future = r.last_accessed + timedelta(days=5)
        returned = r.decay(now=future)
        assert math.isclose(r.strength, returned, abs_tol=1e-9)

    def test_decay_never_below_zero(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="x", stability=0.1)
        far_future = r.last_accessed + timedelta(days=1000)
        strength = r.decay(now=far_future)
        assert strength >= 0.0


# ---------------------------------------------------------------------------
# reinforce()
# ---------------------------------------------------------------------------

class TestReinforce:
    def test_access_count_increments(self):
        r = MemoryRecord(memory_type=MemoryType.SEMANTIC, content="x")
        r.reinforce()
        assert r.access_count == 1
        r.reinforce()
        assert r.access_count == 2

    def test_strength_increases(self):
        r = MemoryRecord(memory_type=MemoryType.SEMANTIC, content="x", strength=0.5)
        r.reinforce()
        assert r.strength > 0.5

    def test_strength_capped_at_1(self):
        r = MemoryRecord(memory_type=MemoryType.SEMANTIC, content="x", strength=0.95)
        r.reinforce()
        assert r.strength <= 1.0

    def test_stability_increases(self):
        r = MemoryRecord(memory_type=MemoryType.SEMANTIC, content="x", stability=1.0)
        old_stability = r.stability
        r.reinforce()
        assert r.stability > old_stability


# ---------------------------------------------------------------------------
# is_forgotten()
# ---------------------------------------------------------------------------

class TestIsForgotten:
    def test_fresh_memory_not_forgotten(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="x")
        assert not r.is_forgotten(threshold=0.05)

    def test_heavily_decayed_is_forgotten(self):
        # 让 last_accessed 远在过去，且 stability 极小
        r = MemoryRecord(
            memory_type=MemoryType.EPISODIC,
            content="x",
            stability=0.1,
        )
        r.last_accessed = datetime.now(timezone.utc) - timedelta(days=10)
        assert r.is_forgotten(threshold=0.05)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_storage_dict_excludes_embedding(self):
        r = MemoryRecord(
            memory_type=MemoryType.SEMANTIC,
            content="test",
            embedding=[0.1, 0.2, 0.3],
        )
        d = r.to_storage_dict()
        assert "embedding" not in d

    def test_to_storage_dict_timestamps_are_strings(self):
        r = MemoryRecord(memory_type=MemoryType.EPISODIC, content="ts test")
        d = r.to_storage_dict()
        assert isinstance(d["created_at"], str)
        assert isinstance(d["updated_at"], str)
        assert isinstance(d["last_accessed"], str)

    def test_to_storage_dict_enum_values_are_strings(self):
        r = MemoryRecord(
            memory_type=MemoryType.EPISODIC,
            content="x",
            importance=ImportanceLevel.HIGH,
        )
        d = r.to_storage_dict()
        assert d["memory_type"] == "episodic"
        assert d["importance"] == "high"

    def test_roundtrip(self):
        r = MemoryRecord(
            memory_type=MemoryType.SEMANTIC,
            content="round trip test",
            importance=ImportanceLevel.CRITICAL,
            stability=2.5,
        )
        d = r.to_storage_dict()
        r2 = MemoryRecord.from_storage_dict(d)
        assert r2.id == r.id
        assert r2.content == r.content
        assert r2.memory_type == r.memory_type
        assert r2.importance == r.importance
        assert math.isclose(r2.stability, r.stability, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# MemoryQuery / MemorySearchResult
# ---------------------------------------------------------------------------

class TestMemoryQuery:
    def test_default_memory_types(self):
        q = MemoryQuery(text="hello")
        assert len(q.memory_types) == len(MemoryType)

    def test_top_k_default(self):
        q = MemoryQuery(text="x")
        assert q.top_k == 5

    def test_custom_params(self):
        q = MemoryQuery(
            text="search term",
            memory_types=[MemoryType.EPISODIC],
            top_k=10,
            min_strength=0.3,
            session_id="s1",
        )
        assert q.memory_types == [MemoryType.EPISODIC]
        assert q.top_k == 10
        assert q.session_id == "s1"
