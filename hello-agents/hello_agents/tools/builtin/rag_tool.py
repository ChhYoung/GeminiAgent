"""
tools/builtin/rag_tool.py — 知识查询工具

允许 Agent 通过 OpenAI Function Calling 主动检索外部知识库：
- search_knowledge    : 在指定知识库中检索参考资料
- list_knowledge_bases: 列出可用的知识库

工具定义格式兼容 OpenAI tool dict（{"type": "function", "function": {...}}）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.rag.knowledge_base import KnowledgeBaseManager

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# OpenAI tool dict 格式
# ------------------------------------------------------------------

RAG_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "在外部知识库中检索相关参考资料。"
                "当需要查阅公司文档、技术手册、政策规定等结构化知识时调用。"
                "与 search_memory 的区别：这里查询的是外部文档库，而非 Agent 的个人记忆。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询文本",
                    },
                    "kb_name": {
                        "type": "string",
                        "description": "知识库名称，若不指定则在所有知识库中搜索",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 3",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "最低相关度阈值 [0, 1]，默认 0.5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_knowledge_bases",
            "description": "列出当前系统中所有可用的知识库及其描述。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# ------------------------------------------------------------------
# 工具处理器
# ------------------------------------------------------------------

class RAGToolHandler:
    """
    处理 OpenAI tool_call，调用 KnowledgeBaseManager 完成检索。

    用法：
        handler = RAGToolHandler(kb_manager)
        result = handler.dispatch(tool_call)
    """

    TOOL_NAMES = {"search_knowledge", "list_knowledge_bases"}

    def __init__(self, kb_manager: KnowledgeBaseManager) -> None:
        self._manager = kb_manager

    def dispatch(self, tool_call: Any) -> str:
        """分发 tool_call 到对应处理器，返回 JSON 字符串。"""
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "search_knowledge":
                return self._search_knowledge(**args)
            elif name == "list_knowledge_bases":
                return self._list_knowledge_bases()
            else:
                return json.dumps({"error": f"Unknown RAG tool: {name}"})
        except Exception as exc:
            logger.exception("RAGTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _search_knowledge(
        self,
        query: str,
        kb_name: str | None = None,
        top_k: int = 3,
        min_score: float = 0.5,
    ) -> str:
        if kb_name:
            kb = self._manager.get(kb_name)
            if kb is None:
                return json.dumps({"error": f"Knowledge base '{kb_name}' not found."})
            results = kb.search(query, top_k=top_k, min_score=min_score)
        else:
            all_kbs = self._manager.list_all()
            results = []
            for kb_meta in all_kbs:
                kb = self._manager.get(kb_meta["name"])
                if kb:
                    results.extend(kb.search(query, top_k=top_k, min_score=min_score))
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:top_k]

        items = [
            {
                "source": r.chunk.source,
                "section": str(r.chunk.page_or_section),
                "content": r.chunk.text[:500],
                "score": round(r.score, 3),
            }
            for r in results
        ]

        context = "\n\n".join(
            f"[来源: {r['source']} §{r['section']}]\n{r['content']}" for r in items
        )

        return json.dumps(
            {
                "results": items,
                "count": len(items),
                "context": context,
            },
            ensure_ascii=False,
        )

    def _list_knowledge_bases(self) -> str:
        kbs = self._manager.list_all()
        items = [
            {
                "name": kb["name"],
                "description": kb.get("description", ""),
                "doc_count": kb.get("doc_count", 0),
                "chunk_count": kb.get("chunk_count", 0),
            }
            for kb in kbs
        ]
        return json.dumps({"knowledge_bases": items, "count": len(items)}, ensure_ascii=False)
