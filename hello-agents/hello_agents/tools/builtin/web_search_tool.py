"""
tools/builtin/web_search_tool.py — Web 搜索工具

优先使用 Tavily（tavily-python），备用 SerpAPI（httpx 调用）。
返回 top-N 结果（title, url, snippet）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# OpenAI tool dict 格式
# ------------------------------------------------------------------

WEB_SEARCH_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "在互联网上搜索实时信息。当需要查询最新新闻、当前事件、"
                "实时数据或训练数据之外的信息时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ------------------------------------------------------------------
# 工具处理器
# ------------------------------------------------------------------

class WebSearchToolHandler:
    """优先 Tavily，备用 SerpAPI 的 Web 搜索处理器。"""

    TOOL_NAMES = {"web_search"}

    def dispatch(self, tool_call: Any) -> str:
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        name = tool_call.function.name
        if name == "web_search":
            return self._web_search(**args)
        return json.dumps({"error": f"Unknown web search tool: {name}"})

    def _web_search(self, query: str, top_n: int = 5) -> str:
        cfg = get_settings()

        # 优先尝试 Tavily
        if cfg.tavily_api_key:
            try:
                return self._search_tavily(query, top_n, cfg.tavily_api_key)
            except Exception as exc:
                logger.warning("Tavily search failed, falling back to SerpAPI: %s", exc)

        # 备用 SerpAPI
        if cfg.serpapi_api_key:
            try:
                return self._search_serpapi(query, top_n, cfg.serpapi_api_key)
            except Exception as exc:
                logger.warning("SerpAPI search failed: %s", exc)

        return json.dumps(
            {"error": "未配置搜索 API（TAVILY_API_KEY 或 SERPAPI_API_KEY）"},
            ensure_ascii=False,
        )

    def _search_tavily(self, query: str, top_n: int, api_key: str) -> str:
        from tavily import TavilyClient  # type: ignore

        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=top_n)
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:500],
            }
            for r in response.get("results", [])
        ]
        return json.dumps(
            {"results": results, "count": len(results), "query": query},
            ensure_ascii=False,
        )

    def _search_serpapi(self, query: str, top_n: int, api_key: str) -> str:
        import httpx

        resp = httpx.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "api_key": api_key,
                "num": top_n,
                "output": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", "")[:500],
            }
            for r in organic[:top_n]
        ]
        return json.dumps(
            {"results": results, "count": len(results), "query": query},
            ensure_ascii=False,
        )
