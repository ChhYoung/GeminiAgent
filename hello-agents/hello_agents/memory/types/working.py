"""
memory/types/working.py — 工作记忆

Session 级别的短期记忆，维护当前对话上下文，带 TTL 自动过期。
完全存储于内存（dict），不依赖外部数据库。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any

from hello_agents.memory.base import ImportanceLevel, MemoryRecord, MemoryType

logger = logging.getLogger(__name__)

_DEFAULT_TTL = int(os.getenv("WORKING_MEMORY_TTL_SECONDS", "3600"))
_DEFAULT_MAX_TOKENS = 8192  # 近似 token 上限（按字符数估算）
_CHARS_PER_TOKEN = 4


class WorkingMemory:
    """
    工作记忆容器。

    特性：
    - 按会话 (session_id) 隔离
    - 每条记录带 TTL，过期自动清除
    - 维护对话窗口（滑动窗口，防止无限增长）
    - 支持置顶（pinned）重要上下文
    """

    def __init__(
        self,
        session_id: str,
        ttl_seconds: int = _DEFAULT_TTL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self.session_id = session_id
        self.ttl_seconds = ttl_seconds
        self.max_tokens = max_tokens

        # id -> (record, expire_at)
        self._records: dict[str, tuple[MemoryRecord, float]] = {}
        # 保持插入顺序的 id 队列
        self._order: deque[str] = deque()
        # 置顶记录 id 集合
        self._pinned: set[str] = set()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        importance: ImportanceLevel = ImportanceLevel.MEDIUM,
        pinned: bool = False,
        ttl_override: int | None = None,
    ) -> MemoryRecord:
        """向工作记忆中追加一条记录。"""
        record = MemoryRecord(
            memory_type=MemoryType.WORKING,
            content=content,
            metadata=metadata or {},
            importance=importance,
            importance_score={"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}[
                importance.value
            ],
            source_session_id=self.session_id,
        )
        ttl = ttl_override if ttl_override is not None else self.ttl_seconds
        expire_at = time.time() + ttl
        self._records[record.id] = (record, expire_at)
        self._order.append(record.id)
        if pinned:
            self._pinned.add(record.id)
        self._trim()
        return record

    def pin(self, memory_id: str) -> None:
        """置顶一条记录，使其不被 trim 移除。"""
        self._pinned.add(memory_id)

    def unpin(self, memory_id: str) -> None:
        self._pinned.discard(memory_id)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def get(self, memory_id: str) -> MemoryRecord | None:
        self._evict_expired()
        entry = self._records.get(memory_id)
        if entry is None:
            return None
        record, _ = entry
        record.reinforce()
        return record

    def get_all(self, include_expired: bool = False) -> list[MemoryRecord]:
        if not include_expired:
            self._evict_expired()
        return [r for r, _ in self._records.values()]

    def get_window(self, last_n: int = 20) -> list[MemoryRecord]:
        """返回最近 N 条有效记忆（对话窗口）。"""
        self._evict_expired()
        valid_ids = [mid for mid in self._order if mid in self._records]
        window_ids = valid_ids[-last_n:]
        return [self._records[mid][0] for mid in window_ids]

    def to_context_string(self, last_n: int = 20) -> str:
        """将工作记忆拼接为可注入到 Prompt 的文本块。"""
        records = self.get_window(last_n)
        lines = []
        for r in records:
            role = r.metadata.get("role", "user")
            lines.append(f"[{role}]: {r.content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    def delete(self, memory_id: str) -> bool:
        if memory_id in self._records:
            del self._records[memory_id]
            self._pinned.discard(memory_id)
            return True
        return False

    def clear(self) -> None:
        self._records.clear()
        self._order.clear()
        self._pinned.clear()

    # ------------------------------------------------------------------
    # 内部维护
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            mid
            for mid, (_, exp) in self._records.items()
            if exp < now and mid not in self._pinned
        ]
        for mid in expired:
            del self._records[mid]
        self._order = deque(mid for mid in self._order if mid in self._records)

    def _trim(self) -> None:
        """按 token 预算移除最老的非置顶记录。"""
        total_chars = sum(len(r.content) for r, _ in self._records.values())
        while total_chars > self.max_tokens * _CHARS_PER_TOKEN and self._order:
            oldest = self._order[0]
            if oldest in self._pinned:
                self._order.rotate(-1)
                continue
            self._order.popleft()
            if oldest in self._records:
                total_chars -= len(self._records[oldest][0].content)
                del self._records[oldest]

    def __len__(self) -> int:
        self._evict_expired()
        return len(self._records)

    def __repr__(self) -> str:
        return f"<WorkingMemory session={self.session_id} items={len(self._records)}>"


class WorkingMemoryStore:
    """多会话工作记忆管理器（按 session_id 隔离）。"""

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL) -> None:
        self._sessions: dict[str, WorkingMemory] = {}
        self.ttl_seconds = ttl_seconds

    def get_session(self, session_id: str) -> WorkingMemory:
        if session_id not in self._sessions:
            self._sessions[session_id] = WorkingMemory(
                session_id=session_id,
                ttl_seconds=self.ttl_seconds,
            )
        return self._sessions[session_id]

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def active_sessions(self) -> list[str]:
        return list(self._sessions.keys())
