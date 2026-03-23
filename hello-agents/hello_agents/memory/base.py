"""
memory/base.py — 记忆系统基础数据模型

包含所有记忆类型共享的字段，以及遗忘曲线（Ebbinghaus）所需的元数据。
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PERCEPTUAL = "perceptual"


class ImportanceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MemoryRecord(BaseModel):
    """所有记忆类型的基础模型。

    遗忘曲线相关字段（Ebbinghaus）：
    - strength        当前记忆强度 [0.0, 1.0]，随时间按指数衰减
    - access_count    被访问/激活的累计次数（每次访问强化记忆）
    - last_accessed   最近一次被读取的时间戳
    - stability       稳定性系数，访问越多稳定性越高，衰减越慢
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    # 时间戳
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_accessed: datetime = Field(default_factory=_utcnow)

    # 遗忘曲线
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="记忆强度")
    stability: float = Field(default=1.0, ge=0.1, description="记忆稳定性（衰减速率倒数）")
    access_count: int = Field(default=0, ge=0, description="累计访问次数")

    # 重要性
    importance: ImportanceLevel = ImportanceLevel.MEDIUM
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)

    # 向量表示（序列化时存为 list）
    embedding: list[float] | None = None

    # 来源溯源
    source_session_id: str | None = None
    source_agent_id: str | None = None

    @field_validator("strength", mode="before")
    @classmethod
    def clamp_strength(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def decay(self, now: datetime | None = None) -> float:
        """按 Ebbinghaus 遗忘曲线计算当前记忆强度。

        公式：strength(t) = e^(-elapsed_days / stability)

        Returns:
            更新后的记忆强度。
        """
        if now is None:
            now = _utcnow()
        elapsed = (now - self.last_accessed).total_seconds()
        elapsed_days = elapsed / 86400.0
        new_strength = math.exp(-elapsed_days / max(self.stability, 0.1))
        self.strength = max(0.0, min(1.0, new_strength))
        return self.strength

    def reinforce(self) -> None:
        """访问/激活记忆，增强强度并提升稳定性。"""
        self.access_count += 1
        self.last_accessed = _utcnow()
        # 每次访问提升稳定性（记忆巩固）
        self.stability = self.stability * 1.2 + 0.1
        self.strength = min(1.0, self.strength + 0.1)
        self.updated_at = _utcnow()

    def is_forgotten(self, threshold: float = 0.05) -> bool:
        """判断记忆是否已衰减至遗忘阈值以下。"""
        self.decay()
        return self.strength < threshold

    def to_storage_dict(self) -> dict[str, Any]:
        """序列化为可存入数据库的字典（排除 embedding 大字段）。"""
        d = self.model_dump(exclude={"embedding"})
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        d["last_accessed"] = self.last_accessed.isoformat()
        d["memory_type"] = self.memory_type.value
        d["importance"] = self.importance.value
        return d

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        for ts_field in ("created_at", "updated_at", "last_accessed"):
            if isinstance(data.get(ts_field), str):
                data[ts_field] = datetime.fromisoformat(data[ts_field])
        return cls(**data)


class MemoryQuery(BaseModel):
    """记忆检索请求。"""

    text: str = Field(..., description="查询文本")
    memory_types: list[MemoryType] = Field(
        default_factory=lambda: list(MemoryType),
        description="要检索的记忆类型列表",
    )
    top_k: int = Field(default=5, ge=1, le=50)
    min_strength: float = Field(default=0.1, ge=0.0, le=1.0, description="强度过滤阈值")
    min_relevance: float = Field(default=0.0, ge=0.0, le=1.0, description="相关度过滤阈值")
    session_id: str | None = None


class MemorySearchResult(BaseModel):
    """单条记忆检索结果。"""

    record: MemoryRecord
    relevance_score: float = Field(ge=0.0, le=1.0, description="语义相关度得分")
    final_score: float = Field(ge=0.0, le=1.0, description="综合得分（相关度 × 强度 × 重要性）")
    source: str = Field(description="来源存储引擎标识")
