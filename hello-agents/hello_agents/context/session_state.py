"""
context/session_state.py — 会话状态追踪 (s05 扩展)

在上下文压缩时提取并保留结构化会话状态，防止压缩后丢失关键信息：
  - 当前目标是什么
  - 已经做了什么
  - 改过哪些文件
  - 还有什么没完成
  - 哪些决定不能丢

集成点：apply_all_layers() 在 Layer 3 触发时调用 extract_session_state()，
将结果以 [会话状态] 系统消息固定在压缩后的 messages 头部。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

# 文件路径启发式匹配（无需 LLM）
_FILE_PATTERN = re.compile(
    r'(?:^|[\s\'"`(])('
    r'(?:[a-zA-Z0-9_\-]+/)*[a-zA-Z0-9_\-]+\.'
    r'(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|txt|sh|sql|go|rs|java|cpp|c|h)'
    r')(?:$|[\s\'"`):,])',
    re.MULTILINE,
)

_STATE_EXTRACT_PROMPT = """\
分析以下对话历史，提取结构化会话状态，严格用 JSON 格式回复：

{{
  "current_goal": "当前正在完成的主要目标（一句话，可为空字符串）",
  "done_actions": ["已完成的关键操作，每项一句话"],
  "changed_files": ["已修改/创建的文件路径"],
  "pending_items": ["还未完成的待办事项"],
  "key_decisions": ["重要决策或约定，压缩后绝不能丢失"]
}}

规则：
- changed_files 只包含明确出现在对话中的文件路径
- key_decisions 聚焦于会影响后续操作的技术决策（如"使用 isoweekday 而非 weekday"）
- 如某字段无内容则填 [] 或 ""
- 只输出 JSON，不要任何解释

对话历史：
{context}
"""


@dataclass
class SessionState:
    """结构化会话状态，跨压缩轮次持久保留。"""

    current_goal: str = ""
    done_actions: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    pending_items: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.current_goal,
            self.done_actions,
            self.changed_files,
            self.pending_items,
            self.key_decisions,
        ])

    def to_block(self) -> str:
        """渲染为可注入 system message 的文本块。"""
        lines = ["[会话状态]"]
        if self.current_goal:
            lines.append(f"当前目标: {self.current_goal}")
        if self.done_actions:
            lines.append("已完成:")
            for a in self.done_actions:
                lines.append(f"  · {a}")
        if self.changed_files:
            lines.append("已修改文件:")
            for f in self.changed_files:
                lines.append(f"  · {f}")
        if self.pending_items:
            lines.append("待完成:")
            for p in self.pending_items:
                lines.append(f"  · {p}")
        if self.key_decisions:
            lines.append("关键决策:")
            for d in self.key_decisions:
                lines.append(f"  · {d}")
        return "\n".join(lines)

    def as_system_message(self) -> dict:
        """生成固定在 messages 头部的 system message。"""
        return {"role": "system", "content": self.to_block()}

    def merge(self, other: "SessionState") -> "SessionState":
        """将两个状态合并（用于增量更新）。"""
        def dedup(lst: list) -> list:
            seen: set = set()
            return [x for x in lst if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]

        return SessionState(
            current_goal=other.current_goal or self.current_goal,
            done_actions=dedup(self.done_actions + other.done_actions),
            changed_files=dedup(self.changed_files + other.changed_files),
            pending_items=dedup(self.pending_items + other.pending_items),
            key_decisions=dedup(self.key_decisions + other.key_decisions),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        return cls(
            current_goal=data.get("current_goal", ""),
            done_actions=list(data.get("done_actions", [])),
            changed_files=list(data.get("changed_files", [])),
            pending_items=list(data.get("pending_items", [])),
            key_decisions=list(data.get("key_decisions", [])),
        )

    @classmethod
    def from_llm_response(cls, text: str) -> "SessionState":
        """解析 LLM 返回的 JSON，容错处理。"""
        # 尝试提取 JSON 块（有时 LLM 会包裹在 ```json ... ``` 中）
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return cls()
        try:
            data = json.loads(match.group(0))
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return cls()

    @classmethod
    def from_system_message(cls, msg: dict) -> "SessionState | None":
        """从已注入的 [会话状态] system message 中解析恢复。"""
        content = msg.get("content", "")
        if "[会话状态]" not in content:
            return None
        # 简单启发式解析（避免再次 LLM 调用）
        state = cls()
        lines = content.splitlines()
        current_section = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("当前目标:"):
                state.current_goal = stripped[len("当前目标:"):].strip()
                current_section = None
            elif stripped == "已完成:":
                current_section = "done"
            elif stripped == "已修改文件:":
                current_section = "files"
            elif stripped == "待完成:":
                current_section = "pending"
            elif stripped == "关键决策:":
                current_section = "decisions"
            elif stripped.startswith("·"):
                item = stripped[1:].strip()
                if current_section == "done":
                    state.done_actions.append(item)
                elif current_section == "files":
                    state.changed_files.append(item)
                elif current_section == "pending":
                    state.pending_items.append(item)
                elif current_section == "decisions":
                    state.key_decisions.append(item)
        return state if not state.is_empty() else None


def extract_files_heuristic(messages: list) -> list:
    """
    启发式从 messages 中提取文件路径（不需要 LLM）。
    扫描 assistant / tool 消息内容。
    """
    found: set = set()
    for msg in messages:
        role = msg.get("role", "")
        if role not in ("assistant", "tool"):
            continue
        content = str(msg.get("content", ""))
        for match in _FILE_PATTERN.finditer(content):
            found.add(match.group(1))
    return sorted(found)


async def extract_session_state(
    messages: list,
    existing_state: "SessionState | None" = None,
) -> "SessionState":
    """
    使用 LLM 从旧消息中提取结构化会话状态。
    若已有 existing_state，将新提取的状态与之合并。

    Args:
        messages:       要分析的旧消息列表（将被压缩的部分）
        existing_state: 上一轮已有的会话状态（如有）

    Returns:
        提取/合并后的 SessionState
    """
    # 快速路径：启发式文件提取
    heuristic_files = extract_files_heuristic(messages)

    # 构造分析文本（截断防止超 token）
    history_text = "\n".join(
        f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:300]}"
        for m in messages
    )

    cfg = get_settings()
    client = openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
    prompt = _STATE_EXTRACT_PROMPT.format(context=history_text[:8000])

    new_state = SessionState()
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg.llm_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
        )
        text = (response.choices[0].message.content or "").strip()
        new_state = SessionState.from_llm_response(text)
        logger.debug("SessionState extracted via LLM: goal=%r", new_state.current_goal)
    except Exception as exc:
        logger.warning("SessionState LLM extraction failed: %s", exc)

    # 合并启发式文件列表
    all_files = list(dict.fromkeys(new_state.changed_files + heuristic_files))
    new_state = SessionState(
        current_goal=new_state.current_goal,
        done_actions=new_state.done_actions,
        changed_files=all_files,
        pending_items=new_state.pending_items,
        key_decisions=new_state.key_decisions,
    )

    # 与历史状态合并
    if existing_state and not existing_state.is_empty():
        new_state = existing_state.merge(new_state)

    return new_state


def find_existing_state(messages: list) -> "SessionState | None":
    """从 messages 中找到并解析上一轮注入的 [会话状态] system message。"""
    for msg in messages:
        if msg.get("role") == "system":
            state = SessionState.from_system_message(msg)
            if state:
                return state
    return None


def inject_state_into_messages(
    messages: list,
    state: "SessionState",
    after_system: bool = True,
) -> list:
    """
    将 SessionState 注入 messages。

    - 若已存在 [会话状态] 消息则更新它（原位替换，不再二次插入）
    - 否则插入到第一个 system 消息之后（after_system=True）或列表头部

    Args:
        messages:     完整 messages 列表
        state:        要注入的状态
        after_system: 无已有状态消息时，是否插入到 system 消息之后（默认 True）

    Returns:
        注入后的新 messages 列表
    """
    if state.is_empty():
        return messages

    state_msg = state.as_system_message()

    # 第一遍：看是否存在旧 [会话状态] 消息
    has_existing = any(
        m.get("role") == "system" and "[会话状态]" in m.get("content", "")
        for m in messages
    )

    if has_existing:
        # 原位替换，其他消息不动
        return [
            state_msg if (m.get("role") == "system" and "[会话状态]" in m.get("content", ""))
            else m
            for m in messages
        ]

    # 无旧消息：插入到第一个 system 消息之后
    result = []
    inserted = False
    for msg in messages:
        result.append(msg)
        if not inserted and after_system and msg.get("role") == "system":
            result.append(state_msg)
            inserted = True

    if not inserted:
        result.insert(0, state_msg)

    return result
