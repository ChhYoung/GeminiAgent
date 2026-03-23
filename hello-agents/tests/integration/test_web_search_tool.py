"""
集成测试: tools/builtin/web_search_tool.py — WebSearchToolHandler
使用 mock 替代网络请求，不依赖真实 API Key。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hello_agents.tools.builtin.web_search_tool import WebSearchToolHandler


def _make_tool_call(name: str, arguments: dict):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


@pytest.fixture
def handler():
    return WebSearchToolHandler()


# ---------------------------------------------------------------------------
# 无 API Key 场景
# ---------------------------------------------------------------------------

class TestNoApiKey:
    def test_no_keys_returns_error(self, handler):
        with patch("hello_agents.tools.builtin.web_search_tool.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.tavily_api_key = None
            settings.serpapi_api_key = None
            mock_cfg.return_value = settings
            tc = _make_tool_call("web_search", {"query": "python news"})
            result = json.loads(handler.dispatch(tc))
        assert "error" in result
        assert "API" in result["error"] or "配置" in result["error"]


# ---------------------------------------------------------------------------
# Tavily 路径
# ---------------------------------------------------------------------------

class TestTavilySearch:
    def test_tavily_called_when_key_present(self, handler):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Python News", "url": "https://example.com", "content": "Some content"}
            ]
        }
        with patch("hello_agents.tools.builtin.web_search_tool.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.tavily_api_key = "fake-tavily-key"
            settings.serpapi_api_key = None
            mock_cfg.return_value = settings
            with patch("hello_agents.tools.builtin.web_search_tool.WebSearchToolHandler._search_tavily") as mock_search:
                mock_search.return_value = json.dumps({
                    "results": [{"title": "Python News", "url": "https://example.com", "snippet": "Some content"}],
                    "count": 1,
                    "query": "python news",
                })
                tc = _make_tool_call("web_search", {"query": "python news"})
                result = json.loads(handler.dispatch(tc))
                mock_search.assert_called_once()

    def test_tavily_result_format(self, handler):
        mock_results = json.dumps({
            "results": [
                {"title": "Test Title", "url": "https://test.com", "snippet": "Test snippet"},
            ],
            "count": 1,
            "query": "test query",
        })
        with patch("hello_agents.tools.builtin.web_search_tool.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.tavily_api_key = "key"
            settings.serpapi_api_key = None
            mock_cfg.return_value = settings
            with patch.object(handler, "_search_tavily", return_value=mock_results):
                tc = _make_tool_call("web_search", {"query": "test"})
                result = json.loads(handler.dispatch(tc))
                assert "results" in result
                assert result["count"] == 1
                assert result["results"][0]["title"] == "Test Title"


# ---------------------------------------------------------------------------
# SerpAPI 备用路径
# ---------------------------------------------------------------------------

class TestSerpAPIFallback:
    def test_serpapi_called_when_tavily_fails(self, handler):
        serpapi_result = json.dumps({
            "results": [{"title": "SerpAPI Result", "url": "https://serpapi.com", "snippet": "..."}],
            "count": 1,
            "query": "test",
        })
        with patch("hello_agents.tools.builtin.web_search_tool.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.tavily_api_key = "fake"
            settings.serpapi_api_key = "serp-key"
            mock_cfg.return_value = settings
            with patch.object(handler, "_search_tavily", side_effect=Exception("Tavily down")):
                with patch.object(handler, "_search_serpapi", return_value=serpapi_result):
                    tc = _make_tool_call("web_search", {"query": "test"})
                    result = json.loads(handler.dispatch(tc))
                    assert "results" in result


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestWebSearchErrorHandling:
    def test_invalid_json_arguments(self, handler):
        tc = MagicMock()
        tc.function.name = "web_search"
        tc.function.arguments = "not-json"
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_unknown_tool_name(self, handler):
        tc = _make_tool_call("unknown_search", {"query": "x"})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_top_n_passed_correctly(self, handler):
        with patch("hello_agents.tools.builtin.web_search_tool.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.tavily_api_key = "key"
            settings.serpapi_api_key = None
            mock_cfg.return_value = settings
            with patch.object(handler, "_search_tavily", return_value='{"results":[],"count":0,"query":"x"}') as mock_s:
                tc = _make_tool_call("web_search", {"query": "x", "top_n": 3})
                handler.dispatch(tc)
                mock_s.assert_called_once_with("x", 3, "key")
