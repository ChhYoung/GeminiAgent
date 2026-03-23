"""
UT: tools/builtin/terminal_tool.py — TerminalToolHandler 安全检查与执行
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hello_agents.tools.builtin.terminal_tool import TerminalToolHandler


def _make_tool_call(name: str, arguments: dict):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments, ensure_ascii=False)
    return tc


@pytest.fixture
def handler():
    return TerminalToolHandler()


# ---------------------------------------------------------------------------
# _is_safe_command
# ---------------------------------------------------------------------------

class TestIsSafeCommand:
    def test_allowed_ls(self, handler):
        safe, _ = handler._is_safe_command("ls -la")
        assert safe is True

    def test_allowed_cat(self, handler):
        safe, _ = handler._is_safe_command("cat /etc/hostname")
        assert safe is True

    def test_allowed_python3(self, handler):
        safe, _ = handler._is_safe_command("python3 -c 'print(1)'")
        assert safe is True

    def test_blocked_rm(self, handler):
        safe, reason = handler._is_safe_command("rm -rf /tmp/test")
        assert safe is False
        assert "rm" in reason.lower()

    def test_blocked_sudo(self, handler):
        safe, reason = handler._is_safe_command("sudo ls")
        assert safe is False

    def test_blocked_curl(self, handler):
        safe, reason = handler._is_safe_command("curl https://example.com")
        assert safe is False

    def test_blocked_redirect_write(self, handler):
        safe, reason = handler._is_safe_command("echo hello > file.txt")
        assert safe is False

    def test_blocked_not_in_whitelist(self, handler):
        safe, reason = handler._is_safe_command("vim /etc/hosts")
        assert safe is False
        assert "vim" in reason.lower() or "白名单" in reason

    def test_empty_command(self, handler):
        safe, reason = handler._is_safe_command("")
        assert safe is False


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------

class TestRunCommand:
    def test_run_echo(self, handler):
        tc = _make_tool_call("run_command", {"command": "echo hello"})
        result = json.loads(handler.dispatch(tc))
        assert "stdout" in result
        assert "hello" in result["stdout"]
        assert result["returncode"] == 0

    def test_blocked_command_returns_error(self, handler):
        tc = _make_tool_call("run_command", {"command": "rm -rf /tmp"})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
        assert "拦截" in result["error"] or "blocked" in result["error"].lower()

    def test_run_with_cwd(self, handler, tmp_path):
        tc = _make_tool_call("run_command", {"command": "pwd", "cwd": str(tmp_path)})
        result = json.loads(handler.dispatch(tc))
        assert str(tmp_path) in result["stdout"]

    def test_stdout_truncation(self, handler):
        # echo 大量内容测试截断标志（不一定超过8000，但验证字段存在）
        tc = _make_tool_call("run_command", {"command": "echo x"})
        result = json.loads(handler.dispatch(tc))
        assert "truncated" in result


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

class TestReadFile:
    def test_read_existing_file(self, handler, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("file content here", encoding="utf-8")
        tc = _make_tool_call("read_file", {"file_path": str(f)})
        result = json.loads(handler.dispatch(tc))
        assert result["content"] == "file content here"
        assert result["truncated"] is False

    def test_read_nonexistent_file(self, handler):
        tc = _make_tool_call("read_file", {"file_path": "/nonexistent/path/file.txt"})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
        assert "不存在" in result["error"]

    def test_read_directory_fails(self, handler, tmp_path):
        tc = _make_tool_call("read_file", {"file_path": str(tmp_path)})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_read_file_large_truncated(self, handler, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 9000, encoding="utf-8")
        tc = _make_tool_call("read_file", {"file_path": str(f)})
        result = json.loads(handler.dispatch(tc))
        assert result["truncated"] is True
        assert len(result["content"]) == 8000

    def test_read_file_has_size(self, handler, tmp_path):
        f = tmp_path / "sized.txt"
        content = "hello world"
        f.write_text(content, encoding="utf-8")
        tc = _make_tool_call("read_file", {"file_path": str(f)})
        result = json.loads(handler.dispatch(tc))
        assert result["size"] == len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------

class TestListDirectory:
    def test_list_existing_directory(self, handler, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        tc = _make_tool_call("list_directory", {"path": str(tmp_path)})
        result = json.loads(handler.dispatch(tc))
        assert result["count"] == 2
        names = {e["name"] for e in result["entries"]}
        assert "a.txt" in names
        assert "b.txt" in names

    def test_list_nonexistent_directory(self, handler):
        tc = _make_tool_call("list_directory", {"path": "/nonexistent_dir_xyz"})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_list_hides_hidden_files_by_default(self, handler, tmp_path):
        (tmp_path / "visible.txt").write_text("v")
        (tmp_path / ".hidden").write_text("h")
        tc = _make_tool_call("list_directory", {"path": str(tmp_path), "show_hidden": False})
        result = json.loads(handler.dispatch(tc))
        names = {e["name"] for e in result["entries"]}
        assert ".hidden" not in names
        assert "visible.txt" in names

    def test_list_shows_hidden_files_when_requested(self, handler, tmp_path):
        (tmp_path / ".hidden").write_text("h")
        tc = _make_tool_call("list_directory", {"path": str(tmp_path), "show_hidden": True})
        result = json.loads(handler.dispatch(tc))
        names = {e["name"] for e in result["entries"]}
        assert ".hidden" in names

    def test_list_distinguishes_file_and_dir(self, handler, tmp_path):
        (tmp_path / "file.txt").write_text("f")
        (tmp_path / "subdir").mkdir()
        tc = _make_tool_call("list_directory", {"path": str(tmp_path)})
        result = json.loads(handler.dispatch(tc))
        entry_types = {e["name"]: e["type"] for e in result["entries"]}
        assert entry_types["file.txt"] == "file"
        assert entry_types["subdir"] == "dir"


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestDispatchErrorHandling:
    def test_invalid_json_arguments(self, handler):
        tc = MagicMock()
        tc.function.name = "run_command"
        tc.function.arguments = "not-json"
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_unknown_tool(self, handler):
        tc = _make_tool_call("unknown_terminal_op", {})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
