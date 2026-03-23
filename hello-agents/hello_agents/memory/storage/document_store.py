"""
memory/storage/document_store.py — SQLite 关系型存储

负责记忆元数据的持久化与溯源查询，不存储高维向量。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from hello_agents.memory.base import MemoryRecord, MemoryType

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/hello_agents.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    memory_type     TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_accessed   TEXT NOT NULL,
    strength        REAL NOT NULL DEFAULT 1.0,
    stability       REAL NOT NULL DEFAULT 1.0,
    access_count    INTEGER NOT NULL DEFAULT 0,
    importance      TEXT NOT NULL DEFAULT 'medium',
    importance_score REAL NOT NULL DEFAULT 0.5,
    source_session_id TEXT,
    source_agent_id   TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_type       ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_session    ON memories(source_session_id);
CREATE INDEX IF NOT EXISTS idx_memories_strength   ON memories(strength);
CREATE INDEX IF NOT EXISTS idx_memories_created    ON memories(created_at);
"""


class DocumentStore:
    """SQLite 元数据存储，支持跨进程的持久化与溯源查询。"""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.debug("DocumentStore schema initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def upsert(self, record: MemoryRecord) -> None:
        """插入或更新一条记忆元数据。"""
        d = record.to_storage_dict()
        d["metadata"] = json.dumps(d.get("metadata", {}), ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    id, memory_type, content, metadata,
                    created_at, updated_at, last_accessed,
                    strength, stability, access_count,
                    importance, importance_score,
                    source_session_id, source_agent_id
                ) VALUES (
                    :id, :memory_type, :content, :metadata,
                    :created_at, :updated_at, :last_accessed,
                    :strength, :stability, :access_count,
                    :importance, :importance_score,
                    :source_session_id, :source_agent_id
                )
                ON CONFLICT(id) DO UPDATE SET
                    content          = excluded.content,
                    metadata         = excluded.metadata,
                    updated_at       = excluded.updated_at,
                    last_accessed    = excluded.last_accessed,
                    strength         = excluded.strength,
                    stability        = excluded.stability,
                    access_count     = excluded.access_count,
                    importance       = excluded.importance,
                    importance_score = excluded.importance_score
                """,
                d,
            )

    def get(self, memory_id: str) -> MemoryRecord | None:
        """按 ID 查询单条记忆。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(dict(row))

    def delete(self, memory_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0

    def list_by_session(
        self,
        session_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """列出某会话的所有记忆（按创建时间倒序）。"""
        sql = "SELECT * FROM memories WHERE source_session_id = ?"
        params: list[Any] = [session_id]
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(dict(r)) for r in rows]

    def list_weak_memories(
        self, threshold: float = 0.1, limit: int = 500
    ) -> list[MemoryRecord]:
        """列出强度低于阈值的记忆（用于垃圾回收）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE strength < ? ORDER BY strength ASC LIMIT ?",
                (threshold, limit),
            ).fetchall()
        return [self._row_to_record(dict(r)) for r in rows]

    def count(self, memory_type: MemoryType | None = None) -> int:
        sql = "SELECT COUNT(*) FROM memories"
        params: list[Any] = []
        if memory_type:
            sql += " WHERE memory_type = ?"
            params.append(memory_type.value)
        with self._conn() as conn:
            return conn.execute(sql, params).fetchone()[0]

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> MemoryRecord:
        row["metadata"] = json.loads(row.get("metadata") or "{}")
        for ts_field in ("created_at", "updated_at", "last_accessed"):
            val = row.get(ts_field)
            if isinstance(val, str):
                row[ts_field] = datetime.fromisoformat(val)
        return MemoryRecord(**row)
