"""
memory/types/perceptual.py — 感知记忆

存储多模态数据（图像、音频描述、文件片段等）的特征向量，
依赖 Qdrant 进行跨模态相似度检索。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

import openai

from hello_agents.config import get_settings
from hello_agents.memory.base import (
    ImportanceLevel,
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)
from hello_agents.memory.embedding import EmbeddingService
from hello_agents.memory.storage.document_store import DocumentStore
from hello_agents.memory.storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class PerceptualMemory:
    """
    感知记忆管理器。

    支持的感知类型：
    - text_description  文本描述（直接嵌入）
    - image             图片（先用 OpenAI Vision 生成描述，再嵌入）
    - file_chunk        文件片段（摘要后嵌入）

    存储结构：
    - Qdrant: 特征向量（perceptual_memory collection）
    - SQLite: 元数据 + 原始描述文本
    """

    def __init__(
        self,
        qdrant: QdrantStore,
        doc_store: DocumentStore,
        embedding: EmbeddingService,
        vision_model: str | None = None,
    ) -> None:
        self._qdrant = qdrant
        self._doc = doc_store
        self._embed = embedding
        cfg = get_settings()
        self._vision_model = vision_model or cfg.llm_model_id
        self._client = openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def store_text(
        self,
        description: str,
        raw_content: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> MemoryRecord:
        """存储一段文本感知（如对话中的关键句）。"""
        return self._store(
            description=description,
            perception_type="text_description",
            metadata={**(metadata or {}), "raw_content": raw_content or description},
            session_id=session_id,
        )

    def store_image(
        self,
        image_path_or_b64: str,
        caption: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> MemoryRecord:
        """
        存储图像感知。
        先用 OpenAI Vision 描述图片，再将描述向量化。
        """
        description = caption
        if description is None:
            description = self._describe_image(image_path_or_b64)

        return self._store(
            description=description,
            perception_type="image",
            metadata={
                **(metadata or {}),
                "image_hash": hashlib.md5(
                    image_path_or_b64[:256].encode()
                ).hexdigest(),
                "caption": description,
            },
            session_id=session_id,
        )

    def store_file_chunk(
        self,
        chunk_text: str,
        file_name: str,
        chunk_index: int = 0,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> MemoryRecord:
        """存储文件片段（经 Chunking 后的感知单元）。"""
        return self._store(
            description=chunk_text,
            perception_type="file_chunk",
            metadata={
                **(metadata or {}),
                "file_name": file_name,
                "chunk_index": chunk_index,
            },
            session_id=session_id,
        )

    def _store(
        self,
        description: str,
        perception_type: str,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            memory_type=MemoryType.PERCEPTUAL,
            content=description,
            metadata={**(metadata or {}), "perception_type": perception_type},
            importance=ImportanceLevel.MEDIUM,
            importance_score=0.5,
            source_session_id=session_id,
        )
        record.embedding = self._embed.embed(description, task_type="RETRIEVAL_DOCUMENT")
        self._qdrant.upsert(record)
        self._doc.upsert(record)
        logger.debug("Perceptual memory stored [%s]: %s", perception_type, record.id)
        return record

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        session_id: str | None = None,
    ) -> list[MemorySearchResult]:
        query_vec = self._embed.embed(query, task_type="RETRIEVAL_QUERY")
        results = self._qdrant.search(
            query_vector=query_vec,
            memory_type=MemoryType.PERCEPTUAL,
            top_k=top_k,
            min_score=min_score,
            session_id=session_id,
        )
        for r in results:
            r.record.reinforce()
            self._doc.upsert(r.record)
        return results

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _describe_image(self, image_path_or_b64: str) -> str:
        """使用 OpenAI Vision 生成图片的文字描述。"""
        try:
            if os.path.isfile(image_path_or_b64):
                with open(image_path_or_b64, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(image_path_or_b64)[1].lstrip(".").lower()
                mime = f"image/{ext or 'jpeg'}"
                image_url = f"data:{mime};base64,{data}"
            else:
                # 假设已是 base64 字符串
                image_url = f"data:image/jpeg;base64,{image_path_or_b64}"

            response = self._client.chat.completions.create(
                model=self._vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                            {
                                "type": "text",
                                "text": "请用简洁的中文描述这张图片的主要内容，不超过100字。",
                            },
                        ],
                    }
                ],
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.warning("Image description failed: %s", exc)
            return "[图像内容无法解析]"
