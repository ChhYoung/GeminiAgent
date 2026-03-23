"""
tools/builtin/note_tool.py — 结构化笔记工具

允许 Agent 像写备忘录一样主动记录/修改持久化信息：
- create_note   : 创建新笔记
- read_note     : 读取指定笔记
- update_note   : 更新笔记内容
- delete_note   : 删除笔记
- list_notes    : 列出所有笔记（支持标签过滤）

使用与 DocumentStore 相同的 SQLite 文件存储。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# OpenAI tool dict 格式
# ------------------------------------------------------------------

NOTE_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "创建一条结构化笔记，用于持久化记录重要信息、待办事项或思考过程。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题"},
                    "content": {"type": "string", "description": "笔记正文内容"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表，用于分类",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "根据笔记 ID 读取完整笔记内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "笔记 ID"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_note",
            "description": "更新已有笔记的标题、内容或标签。",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "笔记 ID"},
                    "title": {"type": "string", "description": "新标题（可选）"},
                    "content": {"type": "string", "description": "新内容（可选）"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "新标签列表（可选）",
                    },
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": "删除指定 ID 的笔记。",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "笔记 ID"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "列出所有笔记，支持按标签过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "按标签过滤（可选），留空返回全部",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 20",
                    },
                },
                "required": [],
            },
        },
    },
]


# ------------------------------------------------------------------
# SQLite 存储
# ------------------------------------------------------------------

def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            tags       TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


# ------------------------------------------------------------------
# 工具处理器
# ------------------------------------------------------------------

class NoteToolHandler:
    """处理笔记相关 tool_call。"""

    TOOL_NAMES = {"create_note", "read_note", "update_note", "delete_note", "list_notes"}

    def __init__(self, db_path: str | None = None) -> None:
        cfg = get_settings()
        self._db_path = db_path or cfg.sqlite_db_path

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "create_note":
                return self._create_note(**args)
            elif name == "read_note":
                return self._read_note(**args)
            elif name == "update_note":
                return self._update_note(**args)
            elif name == "delete_note":
                return self._delete_note(**args)
            elif name == "list_notes":
                return self._list_notes(**args)
            else:
                return json.dumps({"error": f"Unknown note tool: {name}"})
        except Exception as exc:
            logger.exception("NoteTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _create_note(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with _get_conn(self._db_path) as conn:
            cur = conn.execute(
                "INSERT INTO notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, tags_json, now, now),
            )
            note_id = cur.lastrowid
        return json.dumps({"status": "created", "note_id": note_id}, ensure_ascii=False)

    def _read_note(self, note_id: int) -> str:
        with _get_conn(self._db_path) as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return json.dumps({"error": f"Note {note_id} not found"})
        return json.dumps(dict(row), ensure_ascii=False)

    def _update_note(
        self,
        note_id: int,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [now]
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        params.append(note_id)
        with _get_conn(self._db_path) as conn:
            conn.execute(f"UPDATE notes SET {', '.join(updates)} WHERE id = ?", params)
        return json.dumps({"status": "updated", "note_id": note_id}, ensure_ascii=False)

    def _delete_note(self, note_id: int) -> str:
        with _get_conn(self._db_path) as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return json.dumps({"status": "deleted", "note_id": note_id}, ensure_ascii=False)

    def _list_notes(self, tag: str | None = None, limit: int = 20) -> str:
        with _get_conn(self._db_path) as conn:
            if tag:
                rows = conn.execute(
                    "SELECT id, title, tags, created_at, updated_at FROM notes "
                    "WHERE tags LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (f'%"{tag}"%', limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, tags, created_at, updated_at FROM notes "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        items = [dict(r) for r in rows]
        return json.dumps({"notes": items, "count": len(items)}, ensure_ascii=False)
