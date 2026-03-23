"""
UT: tools/builtin/note_tool.py — NoteToolHandler SQLite CRUD
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from hello_agents.tools.builtin.note_tool import NoteToolHandler


def _make_tool_call(name: str, arguments: dict):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments, ensure_ascii=False)
    tc.id = "call_001"
    return tc


@pytest.fixture
def handler(tmp_db):
    return NoteToolHandler(db_path=tmp_db)


# ---------------------------------------------------------------------------
# create_note
# ---------------------------------------------------------------------------

class TestCreateNote:
    def test_create_basic_note(self, handler):
        tc = _make_tool_call("create_note", {"title": "Test", "content": "Hello"})
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "created"
        assert isinstance(result["note_id"], int)

    def test_create_note_with_tags(self, handler):
        tc = _make_tool_call("create_note", {
            "title": "Tagged",
            "content": "Body",
            "tags": ["python", "dev"],
        })
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "created"

    def test_create_multiple_notes_different_ids(self, handler):
        tc1 = _make_tool_call("create_note", {"title": "A", "content": "1"})
        tc2 = _make_tool_call("create_note", {"title": "B", "content": "2"})
        r1 = json.loads(handler.dispatch(tc1))
        r2 = json.loads(handler.dispatch(tc2))
        assert r1["note_id"] != r2["note_id"]


# ---------------------------------------------------------------------------
# read_note
# ---------------------------------------------------------------------------

class TestReadNote:
    def test_read_existing_note(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "Read Me", "content": "content here"})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]

        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_read))
        assert result["title"] == "Read Me"
        assert result["content"] == "content here"

    def test_read_nonexistent_note(self, handler):
        tc = _make_tool_call("read_note", {"note_id": 9999})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
        assert "9999" in result["error"]

    def test_read_note_has_timestamps(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "T", "content": "C"})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]
        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_read))
        assert "created_at" in result
        assert "updated_at" in result


# ---------------------------------------------------------------------------
# update_note
# ---------------------------------------------------------------------------

class TestUpdateNote:
    def test_update_title(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "Old", "content": "body"})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]

        tc_update = _make_tool_call("update_note", {"note_id": note_id, "title": "New"})
        result = json.loads(handler.dispatch(tc_update))
        assert result["status"] == "updated"

        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        updated = json.loads(handler.dispatch(tc_read))
        assert updated["title"] == "New"
        assert updated["content"] == "body"  # 不变

    def test_update_content(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "T", "content": "original"})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]
        tc_update = _make_tool_call("update_note", {"note_id": note_id, "content": "updated"})
        handler.dispatch(tc_update)
        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_read))
        assert result["content"] == "updated"

    def test_update_tags(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "T", "content": "C", "tags": ["old"]})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]
        tc_update = _make_tool_call("update_note", {"note_id": note_id, "tags": ["new_tag"]})
        handler.dispatch(tc_update)
        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_read))
        tags = json.loads(result["tags"])
        assert tags == ["new_tag"]


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------

class TestDeleteNote:
    def test_delete_existing_note(self, handler):
        tc_create = _make_tool_call("create_note", {"title": "Del", "content": "bye"})
        note_id = json.loads(handler.dispatch(tc_create))["note_id"]

        tc_delete = _make_tool_call("delete_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_delete))
        assert result["status"] == "deleted"

        tc_read = _make_tool_call("read_note", {"note_id": note_id})
        result = json.loads(handler.dispatch(tc_read))
        assert "error" in result

    def test_delete_nonexistent_note(self, handler):
        # SQLite DELETE 不报错即使 id 不存在
        tc = _make_tool_call("delete_note", {"note_id": 9999})
        result = json.loads(handler.dispatch(tc))
        assert result["status"] == "deleted"


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------

class TestListNotes:
    def test_list_all_notes(self, handler):
        for i in range(3):
            handler.dispatch(_make_tool_call("create_note", {"title": f"N{i}", "content": "x"}))
        tc = _make_tool_call("list_notes", {})
        result = json.loads(handler.dispatch(tc))
        assert result["count"] == 3
        assert len(result["notes"]) == 3

    def test_list_empty(self, handler):
        tc = _make_tool_call("list_notes", {})
        result = json.loads(handler.dispatch(tc))
        assert result["count"] == 0

    def test_list_with_tag_filter(self, handler):
        handler.dispatch(_make_tool_call("create_note", {
            "title": "Tagged", "content": "x", "tags": ["important"]
        }))
        handler.dispatch(_make_tool_call("create_note", {
            "title": "Untagged", "content": "y"
        }))
        tc = _make_tool_call("list_notes", {"tag": "important"})
        result = json.loads(handler.dispatch(tc))
        assert result["count"] == 1
        assert result["notes"][0]["title"] == "Tagged"

    def test_list_with_limit(self, handler):
        for i in range(5):
            handler.dispatch(_make_tool_call("create_note", {"title": f"N{i}", "content": "x"}))
        tc = _make_tool_call("list_notes", {"limit": 2})
        result = json.loads(handler.dispatch(tc))
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_invalid_json_arguments(self, handler):
        tc = MagicMock()
        tc.function.name = "create_note"
        tc.function.arguments = "not json"
        result = json.loads(handler.dispatch(tc))
        assert "error" in result

    def test_unknown_tool_name(self, handler):
        tc = _make_tool_call("unknown_note_tool", {"x": 1})
        result = json.loads(handler.dispatch(tc))
        assert "error" in result
