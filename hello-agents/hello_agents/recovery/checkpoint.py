"""
recovery/checkpoint.py — 对话快照存储 (s11)

保存/恢复对话状态，支持断点续跑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".agent" / "checkpoints"


class CheckpointStore:
    """
    对话快照存储。

    用法：
        store = CheckpointStore()
        store.save("session-1", messages, step_idx=3)
        messages, idx = store.load("session-1")  # 恢复
    """

    def __init__(self, directory: Path | str = _DEFAULT_DIR) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.json"

    def save(self, session_id: str, messages: list[dict], step_idx: int = 0) -> None:
        """保存对话快照到磁盘。"""
        data = {"session_id": session_id, "step_idx": step_idx, "messages": messages}
        path = self._path(session_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("Checkpoint saved: %s (step %d)", session_id, step_idx)

    def load(self, session_id: str) -> tuple[list[dict], int] | None:
        """
        加载对话快照。

        Returns:
            (messages, step_idx) 或 None（不存在时）
        """
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data["messages"], data.get("step_idx", 0)
        except Exception as exc:
            logger.warning("Failed to load checkpoint %s: %s", session_id, exc)
            return None

    def delete(self, session_id: str) -> bool:
        """删除快照（任务完成后清理）。"""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def list_sessions(self) -> list[str]:
        """列出所有已保存的 session_id。"""
        return [p.stem for p in self._dir.glob("*.json")]
