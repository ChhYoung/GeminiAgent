"""
rag/knowledge_base.py — 知识库管理器

提供知识库的生命周期管理：创建、更新、删除、查询统计。
支持对接企业内部语料库或外部向量库（通过 Qdrant collection 隔离）。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from hello_agents.memory.embedding import EmbeddingService
from hello_agents.rag.document import DocumentParser
from hello_agents.rag.pipeline import RAGPipeline, RetrievalResult

logger = logging.getLogger(__name__)

_META_DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/hello_agents.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    name        TEXT PRIMARY KEY,
    description TEXT,
    collection  TEXT NOT NULL,
    doc_count   INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    config      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id          TEXT PRIMARY KEY,
    kb_name     TEXT NOT NULL,
    source      TEXT NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    indexed_at  TEXT NOT NULL,
    FOREIGN KEY (kb_name) REFERENCES knowledge_bases(name)
);
"""


class KnowledgeBase:
    """
    单个知识库实例。

    通过 KnowledgeBaseManager 创建和管理，不直接实例化。
    """

    def __init__(
        self,
        name: str,
        pipeline: RAGPipeline,
        collection: str,
        description: str = "",
    ) -> None:
        self.name = name
        self.collection = collection
        self.description = description
        self._pipeline = pipeline

    def add_file(
        self,
        path: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """索引文件到知识库，返回写入的 chunk 数量。"""
        count = self._pipeline.index_file(
            path=path,
            collection=self.collection,
            metadata={**(metadata or {}), "kb_name": self.name},
        )
        logger.info("[KB:%s] Indexed file %s (%d chunks)", self.name, path, count)
        return count

    def add_text(
        self,
        text: str,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """索引文本内容到知识库。"""
        return self._pipeline.index_text(
            text=text,
            source=source,
            collection=self.collection,
            metadata={**(metadata or {}), "kb_name": self.name},
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievalResult]:
        """在知识库中检索最相关内容。"""
        return self._pipeline.search(
            query=query,
            collection=self.collection,
            top_k=top_k,
            min_score=min_score,
            filters={"kb_name": self.name},
        )

    def build_context(self, query: str, top_k: int = 5, max_chars: int = 4000) -> str:
        """一步完成检索 + 上下文构建。"""
        results = self.search(query, top_k=top_k)
        return self._pipeline.build_context(results, max_chars=max_chars)

    def __repr__(self) -> str:
        return f"<KnowledgeBase name={self.name} collection={self.collection}>"


class KnowledgeBaseManager:
    """
    知识库管理器。

    统一管理多个知识库实例，元数据持久化到 SQLite。

    用法：
        mgr = KnowledgeBaseManager.from_env()
        kb = mgr.create("company_docs", description="公司内部文档")
        kb.add_file("/docs/handbook.pdf")
        results = kb.search("请假流程")
    """

    def __init__(
        self,
        pipeline: RAGPipeline,
        db_path: str = _META_DB_PATH,
    ) -> None:
        self._pipeline = pipeline
        self._db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_schema()
        self._instances: dict[str, KnowledgeBase] = {}

    @classmethod
    def from_env(cls, api_key: str | None = None) -> "KnowledgeBaseManager":
        from dotenv import load_dotenv
        load_dotenv()
        from hello_agents.memory.embedding import EmbeddingService
        embedding = EmbeddingService(api_key=api_key)
        pipeline = RAGPipeline(embedding=embedding)
        return cls(pipeline=pipeline)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
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
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # 知识库 CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        description: str = "",
        collection: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> KnowledgeBase:
        """创建新知识库（幂等，若已存在则返回现有实例）。"""
        if name in self._instances:
            return self._instances[name]

        col = collection or f"kb_{name}"
        now = datetime.now(timezone.utc).isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO knowledge_bases
                (name, description, collection, created_at, updated_at, config)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, description, col, now, now, json.dumps(config or {})),
            )

        self._pipeline.ensure_collection(col)
        kb = KnowledgeBase(
            name=name,
            pipeline=self._pipeline,
            collection=col,
            description=description,
        )
        self._instances[name] = kb
        logger.info("Knowledge base created: %s (collection=%s)", name, col)
        return kb

    def get(self, name: str) -> KnowledgeBase | None:
        """按名称获取知识库实例。"""
        if name in self._instances:
            return self._instances[name]
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        kb = KnowledgeBase(
            name=row["name"],
            pipeline=self._pipeline,
            collection=row["collection"],
            description=row["description"] or "",
        )
        self._instances[name] = kb
        return kb

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有知识库的元数据。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete(self, name: str, delete_vectors: bool = True) -> bool:
        """删除知识库（可选删除向量数据）。"""
        kb = self.get(name)
        if kb is None:
            return False
        if delete_vectors:
            try:
                self._pipeline.delete_collection(kb.collection)
            except Exception as exc:
                logger.warning("Failed to delete Qdrant collection: %s", exc)
        with self._conn() as conn:
            conn.execute("DELETE FROM kb_documents WHERE kb_name = ?", (name,))
            conn.execute("DELETE FROM knowledge_bases WHERE name = ?", (name,))
        self._instances.pop(name, None)
        logger.info("Knowledge base deleted: %s", name)
        return True
