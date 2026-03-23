"""
memory/router.py — 记忆路由器

负责将一次查询分发到多个记忆存储（Working / Episodic / Semantic / Perceptual），
执行多路召回，对结果进行相关度算分、Re-rank 与上下文融合，返回最终候选集。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from hello_agents.memory.base import MemoryQuery, MemoryRecord, MemorySearchResult, MemoryType
from hello_agents.memory.embedding import EmbeddingService
from hello_agents.memory.types.episodic import EpisodicMemory
from hello_agents.memory.types.perceptual import PerceptualMemory
from hello_agents.memory.types.semantic import SemanticMemory
from hello_agents.memory.types.working import WorkingMemory

logger = logging.getLogger(__name__)


# Re-rank 权重配置（可通过配置文件覆盖）
_RERANK_WEIGHTS: dict[str, float] = {
    "relevance": 0.5,   # 向量相似度
    "strength": 0.3,    # 遗忘曲线强度
    "importance": 0.2,  # 重要性分数
}

# 各记忆类型的先验权重（影响多路融合时的分数调权）
_TYPE_PRIOR: dict[MemoryType, float] = {
    MemoryType.WORKING: 1.2,    # 工作记忆最近最相关
    MemoryType.EPISODIC: 1.0,
    MemoryType.SEMANTIC: 0.9,
    MemoryType.PERCEPTUAL: 0.8,
}


class MemoryRouter:
    """
    多路记忆召回与 Re-rank 引擎。

    工作流程：
    1. 将 MemoryQuery 广播到所有启用的记忆模块
    2. 汇总所有候选结果
    3. 去重（按 memory_id 保留最高分）
    4. 使用加权公式重新打分
    5. 按 final_score 排序，返回 top_k 结果
    6. 可选：注入 GraphRAG 上下文补充语义关联
    """

    def __init__(
        self,
        embedding: EmbeddingService,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
        perceptual: PerceptualMemory | None = None,
        working: WorkingMemory | None = None,
        enable_graph_rag: bool = True,
    ) -> None:
        self._embed = embedding
        self._episodic = episodic
        self._semantic = semantic
        self._perceptual = perceptual
        self._working = working
        self._enable_graph_rag = enable_graph_rag

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def retrieve(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """同步多路检索 + Re-rank。"""
        candidates: list[MemorySearchResult] = []

        # Working Memory（精确匹配，不走向量）
        if MemoryType.WORKING in query.memory_types and self._working is not None:
            wm_results = self._search_working(query)
            candidates.extend(wm_results)

        # Episodic Memory
        if MemoryType.EPISODIC in query.memory_types and self._episodic is not None:
            ep_results = self._episodic.search(
                query=query.text,
                top_k=query.top_k * 2,
                min_strength=query.min_strength,
                min_score=query.min_relevance,
                session_id=query.session_id,
            )
            candidates.extend(ep_results)

        # Semantic Memory
        if MemoryType.SEMANTIC in query.memory_types and self._semantic is not None:
            sem_results = self._semantic.search(
                query=query.text,
                top_k=query.top_k,
                min_score=query.min_relevance,
            )
            # 可选：GraphRAG 扩展
            if self._enable_graph_rag:
                sem_results = self._enrich_with_graph(query.text, sem_results)
            candidates.extend(sem_results)

        # Perceptual Memory
        if MemoryType.PERCEPTUAL in query.memory_types and self._perceptual is not None:
            perc_results = self._perceptual.search(
                query=query.text,
                top_k=query.top_k,
                min_score=query.min_relevance,
                session_id=query.session_id,
            )
            candidates.extend(perc_results)

        return self._rerank(candidates, top_k=query.top_k)

    async def aretrieve(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """异步并发多路检索 + Re-rank。"""
        tasks: list[asyncio.coroutine] = []

        async def _run_episodic():
            if MemoryType.EPISODIC in query.memory_types and self._episodic:
                return await asyncio.to_thread(
                    self._episodic.search,
                    query.text,
                    query.top_k * 2,
                    query.min_strength,
                    query.min_relevance,
                    query.session_id,
                )
            return []

        async def _run_semantic():
            if MemoryType.SEMANTIC in query.memory_types and self._semantic:
                results = await asyncio.to_thread(
                    self._semantic.search, query.text, query.top_k, query.min_relevance
                )
                if self._enable_graph_rag:
                    results = self._enrich_with_graph(query.text, results)
                return results
            return []

        async def _run_perceptual():
            if MemoryType.PERCEPTUAL in query.memory_types and self._perceptual:
                return await asyncio.to_thread(
                    self._perceptual.search,
                    query.text,
                    query.top_k,
                    query.min_relevance,
                    query.session_id,
                )
            return []

        ep, sem, perc = await asyncio.gather(
            _run_episodic(), _run_semantic(), _run_perceptual()
        )

        candidates: list[MemorySearchResult] = []
        if MemoryType.WORKING in query.memory_types and self._working:
            candidates.extend(self._search_working(query))
        candidates.extend(ep)
        candidates.extend(sem)
        candidates.extend(perc)

        return self._rerank(candidates, top_k=query.top_k)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _search_working(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """从工作记忆中做简单关键词相关度匹配。"""
        if self._working is None:
            return []
        query_lower = query.text.lower()
        results: list[MemorySearchResult] = []
        for record in self._working.get_all():
            overlap = self._keyword_overlap(query_lower, record.content.lower())
            if overlap > 0:
                final = overlap * record.strength * record.importance_score
                results.append(
                    MemorySearchResult(
                        record=record,
                        relevance_score=overlap,
                        final_score=final,
                        source="working_memory",
                    )
                )
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[: query.top_k]

    def _rerank(
        self, candidates: list[MemorySearchResult], top_k: int
    ) -> list[MemorySearchResult]:
        """去重 + 加权 Re-rank。"""
        # 按 id 去重，保留最高 final_score
        deduped: dict[str, MemorySearchResult] = {}
        for r in candidates:
            mid = r.record.id
            if mid not in deduped or r.final_score > deduped[mid].final_score:
                deduped[mid] = r

        # 重新计算 final_score
        w = _RERANK_WEIGHTS
        for r in deduped.values():
            prior = _TYPE_PRIOR.get(r.record.memory_type, 1.0)
            r.final_score = (
                w["relevance"] * r.relevance_score
                + w["strength"] * r.record.strength
                + w["importance"] * r.record.importance_score
            ) * prior

        ranked = sorted(deduped.values(), key=lambda r: r.final_score, reverse=True)
        return ranked[:top_k]

    def _enrich_with_graph(
        self,
        query_text: str,
        results: list[MemorySearchResult],
    ) -> list[MemorySearchResult]:
        """通过 GraphRAG 为语义记忆结果注入图邻居上下文。"""
        if self._semantic is None:
            return results
        for r in results:
            entities = r.record.metadata.get("entities", [])
            graph_ctx: list[str] = []
            for ent in entities[:3]:
                name = ent.get("name", "")
                if name:
                    neighbors = self._semantic.graph_search(name, depth=1)
                    for n in neighbors[:5]:
                        graph_ctx.append(
                            f"{n['entity'].get('name')} "
                            f"-[{n['relation'].get('relation', '?')}]-> "
                            f"{n['neighbor'].get('name')}"
                        )
            if graph_ctx:
                r.record.metadata["graph_context"] = graph_ctx
        return results

    @staticmethod
    def _keyword_overlap(query: str, text: str) -> float:
        """简单 Jaccard 关键词重叠率。"""
        q_words = set(query.split())
        t_words = set(text.split())
        if not q_words:
            return 0.0
        intersection = q_words & t_words
        return len(intersection) / len(q_words)

    # ------------------------------------------------------------------
    # 上下文融合
    # ------------------------------------------------------------------

    def build_context(
        self,
        results: list[MemorySearchResult],
        max_chars: int = 4000,
    ) -> str:
        """将检索结果融合为可注入 Prompt 的上下文字符串。"""
        lines: list[str] = ["### 相关记忆上下文 ###"]
        total = 0
        for i, r in enumerate(results):
            rec = r.record
            line = (
                f"[{i+1}] [{rec.memory_type.value.upper()}] "
                f"(score={r.final_score:.2f}, strength={rec.strength:.2f})\n"
                f"  {rec.content}"
            )
            # 附加图谱上下文
            graph_ctx = rec.metadata.get("graph_context", [])
            if graph_ctx:
                line += "\n  [图谱关联] " + " | ".join(graph_ctx[:3])

            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)
