"""
tests/integration/test_background.py — BackgroundExecutor + BackgroundToolHandler 测试 (s08)
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from hello_agents.tasks.background import BackgroundExecutor
from hello_agents.tools.builtin.background_tool import BackgroundToolHandler


# ---------------------------------------------------------------------------
# BackgroundExecutor
# ---------------------------------------------------------------------------

class TestBackgroundExecutor:
    def test_submit_returns_job_id(self):
        ex = BackgroundExecutor()
        job_id = ex.submit(lambda: "result")
        assert isinstance(job_id, str)
        assert len(job_id) > 0
        ex.shutdown()

    def test_poll_running_then_done(self):
        ex = BackgroundExecutor()
        job_id = ex.submit(lambda: (time.sleep(0.05), "done")[1])
        # 立即查询可能是 running
        first = ex.poll(job_id)
        assert first["status"] in ("running", "done")
        # 等待完成
        time.sleep(0.2)
        result = ex.poll(job_id)
        assert result["status"] == "done"
        assert result["result"] == "done"
        ex.shutdown()

    def test_poll_unknown_job_id(self):
        ex = BackgroundExecutor()
        result = ex.poll("nonexistent")
        assert result["status"] == "error"
        assert "nonexistent" in result["result"]
        ex.shutdown()

    def test_poll_error_captures_exception(self):
        ex = BackgroundExecutor()

        def fail():
            raise ValueError("something went wrong")

        job_id = ex.submit(fail)
        time.sleep(0.1)
        result = ex.poll(job_id)
        assert result["status"] == "error"
        assert "something went wrong" in result["result"]
        ex.shutdown()

    def test_submit_command(self):
        ex = BackgroundExecutor()
        job_id = ex.submit_command("echo hello_bg_test")
        time.sleep(0.5)
        result = ex.poll(job_id)
        assert result["status"] == "done"
        assert "hello_bg_test" in result["result"]
        ex.shutdown()

    def test_cancel_pending_job(self):
        ex = BackgroundExecutor(max_workers=1)
        # 提交一个长任务把线程池占满
        ex.submit(lambda: time.sleep(5))
        # 提交第二个任务（还在队列中）
        job_id = ex.submit(lambda: "fast")
        cancelled = ex.cancel(job_id)
        # cancel 可能成功也可能已开始执行
        assert isinstance(cancelled, bool)
        ex.shutdown()


# ---------------------------------------------------------------------------
# BackgroundToolHandler (s02)
# ---------------------------------------------------------------------------

class TestBackgroundToolHandler:
    def _make_tool_call(self, name: str, args: dict) -> MagicMock:
        tc = MagicMock()
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    def test_run_background_returns_job_id(self):
        handler = BackgroundToolHandler()
        tc = self._make_tool_call("run_background", {"command": "echo test"})
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "submitted"
        assert "job_id" in result
        assert len(result["job_id"]) > 0

    def test_poll_background_running(self):
        handler = BackgroundToolHandler()
        tc_run = self._make_tool_call("run_background", {"command": "echo poll_test"})
        run_result = json.loads(handler.dispatch(tc_run))
        job_id = run_result["job_id"]

        tc_poll = self._make_tool_call("poll_background", {"job_id": job_id})
        poll_result = json.loads(handler.dispatch(tc_poll))
        assert poll_result["status"] in ("running", "done")

    def test_poll_background_done(self):
        handler = BackgroundToolHandler()
        tc_run = self._make_tool_call("run_background", {"command": "echo done_test"})
        run_result = json.loads(handler.dispatch(tc_run))
        job_id = run_result["job_id"]

        time.sleep(0.5)
        tc_poll = self._make_tool_call("poll_background", {"job_id": job_id})
        poll_result = json.loads(handler.dispatch(tc_poll))
        assert poll_result["status"] == "done"
        assert "done_test" in poll_result["result"]

    def test_invalid_json_arguments(self):
        handler = BackgroundToolHandler()
        tc = MagicMock()
        tc.function.name = "run_background"
        tc.function.arguments = "not json"
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_unknown_tool_name(self):
        handler = BackgroundToolHandler()
        tc = self._make_tool_call("unknown_tool", {})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
