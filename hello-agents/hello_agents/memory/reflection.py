"""
memory/reflection.py — 反思与巩固引擎

后台定期将情景记忆（Episodic）中的高价值事件提炼压缩为
语义记忆（Semantic）知识图谱条目，并衰减低价值记忆。

核心思路（受 Park et al. "Generative Agents" 论文启发）：
1. 周期性触发（每隔 N 秒 或 累积 M 条新 Episodic 后触发）
2. 用 LLM 对一批情景记忆做摘要/实体抽取
3. 将结果写入 SemanticMemory
4. 更新 Episodic 记忆的 stability（已被提炼 → 稳定性降低，可逐步遗忘）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import openai

from hello_agents.config import get_settings
from hello_agents.memory.base import ImportanceLevel, MemoryRecord
from hello_agents.memory.events import EventBus, EventType, MemoryEvent
from hello_agents.memory.types.episodic import EpisodicMemory
from hello_agents.memory.types.semantic import SemanticMemory

# 延迟导入以避免循环依赖
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from hello_agents.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_REFLECTION_INTERVAL = int(os.getenv("REFLECTION_INTERVAL_SECONDS", "300"))
_BATCH_SIZE = 10
_MIN_IMPORTANCE = ImportanceLevel.MEDIUM

_EXTRACT_PROMPT = """
你是一个记忆提炼助手。以下是一批情景记忆（事件记录），请从中提炼出：
1. 关键实体列表（格式：[{"name": "实体名", "type": "实体类型"}]）
2. 实体间的关系列表（格式：[{"from": "A", "to": "B", "rel": "关系", "weight": 0.9}]）
3. 一句话摘要（不超过100字）

情景记忆：
{episodes}

请严格以 JSON 格式返回，结构如下：
{{
  "summary": "...",
  "entities": [...],
  "relations": [...]
}}
不要添加任何额外说明。
"""


class ReflectionEngine:
    """
    反思与巩固引擎。

    使用方式：
        engine = ReflectionEngine(episodic, semantic, event_bus)
        await engine.start()   # 启动后台调度
        # ...
        await engine.stop()
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        event_bus: EventBus | None = None,
        interval_seconds: int = _REFLECTION_INTERVAL,
        model: str | None = None,
        api_key: str | None = None,
        manager: "MemoryManager | None" = None,
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic
        self._bus = event_bus
        self._interval = interval_seconds
        self._manager = manager

        cfg = get_settings()
        self._model = model or cfg.llm_model_id
        self._client = openai.OpenAI(
            api_key=api_key or cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )

        self._running = False
        self._task: asyncio.Task | None = None
        self._new_episodic_count = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._scheduler(), name="reflection-engine"
        )
        logger.info("ReflectionEngine started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReflectionEngine stopped.")

    def notify_new_episodic(self) -> None:
        """由外部调用，通知有新的情景记忆写入（触发提前反思）。"""
        self._new_episodic_count += 1

    # ------------------------------------------------------------------
    # 调度循环
    # ------------------------------------------------------------------

    async def _scheduler(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self.reflect()
                if self._manager is not None:
                    deleted = await asyncio.to_thread(self._manager.gc)
                    if deleted:
                        logger.info("Scheduled GC removed %d forgotten memories.", deleted)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("ReflectionEngine error: %s", exc)

    # ------------------------------------------------------------------
    # 核心反思逻辑
    # ------------------------------------------------------------------

    async def reflect(self, session_id: str | None = None) -> list[str]:
        """
        执行一轮反思：
        1. 从情景记忆中取出最近 N 条高重要性记录
        2. 用 LLM 提炼为语义事实
        3. 写入语义记忆

        Returns:
            新创建的语义记忆 ID 列表
        """
        logger.info("Starting reflection cycle...")

        if self._bus:
            await self._bus.publish(
                MemoryEvent(type=EventType.REFLECTION_TRIGGERED, source="reflection_engine")
            )

        candidates = await asyncio.to_thread(
            self._episodic.get_by_session,
            session_id or "",
            _BATCH_SIZE,
        ) if session_id else await self._get_high_value_episodes()

        if not candidates:
            logger.info("No candidates for reflection.")
            return []

        new_semantic_ids: list[str] = []
        batch_size = min(5, len(candidates))
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            try:
                semantic_id = await self._distill_batch(batch)
                if semantic_id:
                    new_semantic_ids.append(semantic_id)
            except Exception as exc:
                logger.warning("Distillation failed for batch %d: %s", i, exc)

        self._new_episodic_count = 0
        logger.info("Reflection completed. Created %d semantic memories.", len(new_semantic_ids))

        if self._bus:
            await self._bus.publish(
                MemoryEvent(
                    type=EventType.REFLECTION_COMPLETED,
                    payload={"new_semantic_count": len(new_semantic_ids)},
                    source="reflection_engine",
                )
            )

        return new_semantic_ids

    async def _get_high_value_episodes(self) -> list[MemoryRecord]:
        """从 SQLite 取出近期高重要性且尚未提炼的情景记忆。"""
        records = await asyncio.to_thread(
            self._episodic._doc.list_by_session,
            "",
            None,
            _BATCH_SIZE,
        )
        return [
            r for r in records
            if r.importance in (ImportanceLevel.HIGH, ImportanceLevel.CRITICAL)
            and not r.metadata.get("distilled", False)
        ]

    async def _distill_batch(
        self, records: list[MemoryRecord]
    ) -> str | None:
        """用 LLM 对一批情景记忆提炼语义事实。"""
        episodes_text = "\n".join(
            f"[{i+1}] {r.content}" for i, r in enumerate(records)
        )
        prompt = _EXTRACT_PROMPT.format(episodes=episodes_text)

        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
            if match:
                data = json.loads(match.group(1))
            else:
                raise

        summary = data.get("summary", "")
        entities = data.get("entities", [])
        relations = data.get("relations", [])

        if not summary:
            return None

        sem_record = await asyncio.to_thread(
            self._semantic.store_fact,
            summary,
            entities,
            relations,
            {
                "source_episode_ids": [r.id for r in records],
                "distilled_at": datetime.now(timezone.utc).isoformat(),
            },
            ImportanceLevel.HIGH,
            records[0].source_session_id if records else None,
        )

        for r in records:
            r.metadata["distilled"] = True
            r.metadata["derived_semantic_id"] = sem_record.id
            await asyncio.to_thread(self._episodic._doc.upsert, r)

        logger.debug("Distilled %d episodes -> semantic: %s", len(records), sem_record.id)
        return sem_record.id
