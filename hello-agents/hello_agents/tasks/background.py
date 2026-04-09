"""
tasks/background.py — 后台任务执行器 (s13)

慢操作（如 shell 命令、网络请求）放到线程池执行，
主 agent 继续思考，通过 poll() 查询进度。

v5 新增 (s13)：
  - on_complete(): 注册完成回调
  - _callbacks: 任务完成时自动触发
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


class BackgroundExecutor:
    """
    线程池后台执行器。

    用法：
        executor = BackgroundExecutor()
        job_id = executor.submit_command("sleep 3 && echo done")
        # agent 继续工作 ...
        result = executor.poll(job_id)
        # {"status": "running"|"done"|"error", "result": ...}
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future] = {}
        self._callbacks: dict[str, List[Callable[[dict], None]]] = {}  # v5 s13

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> str:
        """提交任意可调用对象到后台执行，返回 job_id。"""
        job_id = str(uuid.uuid4())[:8]
        future = self._pool.submit(fn, *args, **kwargs)
        self._futures[job_id] = future
        # v5 s13: 完成时触发回调
        future.add_done_callback(lambda f: self._on_done(job_id, f))
        logger.info("Background job %s submitted", job_id)
        return job_id

    def on_complete(self, job_id: str, callback: Callable[[dict], None]) -> None:
        """注册任务完成回调（v5 s13）。任务已完成时立即触发。"""
        if job_id not in self._callbacks:
            self._callbacks[job_id] = []
        self._callbacks[job_id].append(callback)
        # 如果任务已完成，立即触发
        future = self._futures.get(job_id)
        if future and future.done():
            self._on_done(job_id, future)

    def _on_done(self, job_id: str, future: Future) -> None:
        """内部：任务完成时调用所有注册回调。"""
        result = self.poll(job_id)
        for cb in self._callbacks.get(job_id, []):
            try:
                cb(result)
            except Exception as exc:
                logger.warning("Background callback error for %s: %s", job_id, exc)

    def submit_command(self, command: str, timeout: int = 60) -> str:
        """提交 shell 命令到后台执行，返回 job_id。"""

        def _run() -> str:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]: {result.stderr}"
            return output

        return self.submit(_run)

    def poll(self, job_id: str) -> dict:
        """
        查询后台任务状态。

        Returns:
            {"status": "running"|"done"|"error", "result": str | None}
        """
        future = self._futures.get(job_id)
        if future is None:
            return {"status": "error", "result": f"Unknown job_id: {job_id}"}

        if not future.done():
            return {"status": "running", "result": None}

        try:
            result = future.result()
            return {"status": "done", "result": result}
        except Exception as exc:
            return {"status": "error", "result": str(exc)}

    def cancel(self, job_id: str) -> bool:
        """尝试取消尚未开始的任务。"""
        future = self._futures.get(job_id)
        return future.cancel() if future else False

    def shutdown(self) -> None:
        """关闭线程池（不等待）。"""
        self._pool.shutdown(wait=False)
