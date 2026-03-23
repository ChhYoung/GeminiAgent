"""
rag/pipeline.py — 知识检索管道

完整的 RAG 流程：
    文档 -> 解析 -> Chunking -> Embedding -> 写入 Qdrant -> 检索 -> 生成答案
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from hello_agents.memory.embedding import EmbeddingService
from hello_agents.rag.document import DocumentChunk, DocumentParser, TextSplitter

logger = logging.getLogger(__name__)

_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
_QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
_EMBED_DIM = int(os.getenv("EMBEDDING_DIMENSION", "768"))
_DEFAULT_KB_COLLECTION = "rag_knowledge_base"


@dataclass
class RetrievalResult:
    """单条 RAG 检索结果。"""

    chunk: DocumentChunk
    score: float
    collection: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class RAGPipeline:
    """
    RAG 知识检索管道。

    用法示例：
        pipeline = RAGPipeline(embedding_service)
        pipeline.index_file("/path/to/doc.pdf", collection="my_kb")
        results = pipeline.search("Python 异步编程", collection="my_kb")
        context = pipeline.build_context(results)
    """

    def __init__(
        self,
        embedding: EmbeddingService,
        qdrant_url: str = _QDRANT_URL,
        qdrant_api_key: str | None = _QDRANT_API_KEY,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> None:
        self._embed = embedding
        self._client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        self._parser = DocumentParser()
        self._splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._dimension = embedding.dimension

    # ------------------------------------------------------------------
    # 集合管理
    # ------------------------------------------------------------------

    def ensure_collection(
        self, collection: str = _DEFAULT_KB_COLLECTION
    ) -> None:
        """确保 Qdrant collection 存在。"""
        existing = {c.name for c in self._client.get_collections().collections}
        if collection not in existing:
            self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=self._dimension,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created RAG collection: %s", collection)

    def delete_collection(self, collection: str) -> None:
        self._client.delete_collection(collection)
        logger.info("Deleted RAG collection: %s", collection)

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    def index_file(
        self,
        path: str,
        collection: str = _DEFAULT_KB_COLLECTION,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """解析文件并将所有 chunks 索引到 Qdrant。返回写入的 chunk 数量。"""
        self.ensure_collection(collection)
        raw_chunks = self._parser.parse(path)
        chunks = self._splitter.split_chunks(raw_chunks)
        return self._index_chunks(chunks, collection, metadata)

    def index_text(
        self,
        text: str,
        source: str = "inline",
        collection: str = _DEFAULT_KB_COLLECTION,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """直接索引文本内容。"""
        self.ensure_collection(collection)
        raw_chunks = self._parser.parse_text(text, source=source)
        chunks = self._splitter.split_chunks(raw_chunks)
        return self._index_chunks(chunks, collection, metadata)

    def _index_chunks(
        self,
        chunks: list[DocumentChunk],
        collection: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> int:
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        vectors = self._embed.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")

        import uuid

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "text": chunk.text,
                    "source": chunk.source,
                    "page_or_section": str(chunk.page_or_section),
                    **(extra_metadata or {}),
                    **chunk.metadata,
                },
            )
            for chunk, vec in zip(chunks, vectors)
        ]

        # 分批上传
        batch_size = 100
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=collection,
                points=points[i : i + batch_size],
            )

        logger.info("Indexed %d chunks into collection '%s'", len(chunks), collection)
        return len(chunks)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        collection: str = _DEFAULT_KB_COLLECTION,
        top_k: int = 5,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """语义检索知识库，返回最相关的 chunks。"""
        query_vec = self._embed.embed(query, task_type="RETRIEVAL_QUERY")

        qdrant_filter = None
        if filters:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        hits = self._client.search(
            collection_name=collection,
            query_vector=query_vec,
            limit=top_k,
            score_threshold=min_score,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        results: list[RetrievalResult] = []
        for hit in hits:
            payload = dict(hit.payload)
            chunk = DocumentChunk(
                text=payload.pop("text", ""),
                source=payload.pop("source", ""),
                page_or_section=payload.pop("page_or_section", 0),
                metadata=payload,
            )
            results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=float(hit.score),
                    collection=collection,
                )
            )
        return results

    # ------------------------------------------------------------------
    # 上下文构建
    # ------------------------------------------------------------------

    def build_context(
        self,
        results: list[RetrievalResult],
        max_chars: int = 4000,
        with_source: bool = True,
    ) -> str:
        """将检索结果拼接为 Prompt 上下文块。"""
        lines = ["### 知识库参考资料 ###"]
        total = 0
        for i, r in enumerate(results):
            source_tag = f" [来源: {r.chunk.source}, §{r.chunk.page_or_section}]" if with_source else ""
            line = f"[{i+1}]{source_tag}\n{r.chunk.text}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n\n".join(lines)
