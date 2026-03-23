"""
conftest.py — 共享 pytest fixtures
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 确保测试时不需要真实 .env（单元测试用 mock 替代）
os.environ.setdefault("LLM_API_KEY", "test-api-key")
os.environ.setdefault("LLM_MODEL_ID", "qwen3-max-2026-01-23")
os.environ.setdefault("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """返回临时 SQLite 数据库路径。"""
    return str(tmp_path / "test.db")


@pytest.fixture
def mock_tool_call():
    """创建 mock OpenAI tool_call 对象的工厂函数。"""
    def _make(name: str, arguments: str, call_id: str = "call_001"):
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = name
        tc.function.arguments = arguments
        return tc
    return _make
