"""
tests/unit/test_session_state.py — 会话状态追踪测试
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hello_agents.context.session_state import (
    SessionState,
    extract_files_heuristic,
    extract_session_state,
    find_existing_state,
    inject_state_into_messages,
)


# ──────────────────────────────────────────────────────────────────────────────
# SessionState dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionState:
    def test_is_empty_when_all_fields_default(self):
        assert SessionState().is_empty()

    def test_not_empty_with_goal(self):
        assert not SessionState(current_goal="fix bug").is_empty()

    def test_not_empty_with_files(self):
        assert not SessionState(changed_files=["foo.py"]).is_empty()

    def test_to_block_contains_all_sections(self):
        s = SessionState(
            current_goal="implement feature X",
            done_actions=["wrote tests", "added handler"],
            changed_files=["hello_agents/agent.py"],
            pending_items=["update docs"],
            key_decisions=["use isoweekday not weekday"],
        )
        block = s.to_block()
        assert "[会话状态]" in block
        assert "当前目标: implement feature X" in block
        assert "已完成:" in block
        assert "· wrote tests" in block
        assert "已修改文件:" in block
        assert "· hello_agents/agent.py" in block
        assert "待完成:" in block
        assert "· update docs" in block
        assert "关键决策:" in block
        assert "· use isoweekday not weekday" in block

    def test_to_block_skips_empty_sections(self):
        s = SessionState(current_goal="goal only")
        block = s.to_block()
        assert "已完成:" not in block
        assert "待完成:" not in block

    def test_as_system_message_has_correct_role(self):
        s = SessionState(current_goal="test")
        msg = s.as_system_message()
        assert msg["role"] == "system"
        assert "[会话状态]" in msg["content"]

    def test_merge_combines_lists(self):
        a = SessionState(
            current_goal="old goal",
            done_actions=["action1"],
            changed_files=["file1.py"],
        )
        b = SessionState(
            current_goal="new goal",
            done_actions=["action2"],
            changed_files=["file2.py"],
        )
        merged = a.merge(b)
        assert merged.current_goal == "new goal"  # other overrides
        assert "action1" in merged.done_actions
        assert "action2" in merged.done_actions
        assert "file1.py" in merged.changed_files
        assert "file2.py" in merged.changed_files

    def test_merge_deduplicates(self):
        a = SessionState(done_actions=["do X", "do Y"])
        b = SessionState(done_actions=["do Y", "do Z"])
        merged = a.merge(b)
        assert merged.done_actions.count("do Y") == 1

    def test_merge_preserves_goal_if_other_empty(self):
        a = SessionState(current_goal="keep me")
        b = SessionState()
        merged = a.merge(b)
        assert merged.current_goal == "keep me"

    def test_from_llm_response_valid_json(self):
        response = """{
            "current_goal": "write tests",
            "done_actions": ["created file"],
            "changed_files": ["agent.py"],
            "pending_items": ["run tests"],
            "key_decisions": ["use pytest"]
        }"""
        s = SessionState.from_llm_response(response)
        assert s.current_goal == "write tests"
        assert s.done_actions == ["created file"]
        assert s.changed_files == ["agent.py"]
        assert s.pending_items == ["run tests"]
        assert s.key_decisions == ["use pytest"]

    def test_from_llm_response_with_markdown_wrapper(self):
        response = '```json\n{"current_goal": "fix bug"}\n```'
        s = SessionState.from_llm_response(response)
        assert s.current_goal == "fix bug"

    def test_from_llm_response_invalid_json(self):
        s = SessionState.from_llm_response("not json at all")
        assert s.is_empty()

    def test_from_system_message_roundtrip(self):
        original = SessionState(
            current_goal="implement session state",
            done_actions=["wrote dataclass"],
            changed_files=["session_state.py"],
            pending_items=["write tests"],
            key_decisions=["use LLM for extraction"],
        )
        msg = original.as_system_message()
        recovered = SessionState.from_system_message(msg)
        assert recovered is not None
        assert recovered.current_goal == "implement session state"
        assert "wrote dataclass" in recovered.done_actions
        assert "session_state.py" in recovered.changed_files
        assert "write tests" in recovered.pending_items
        assert "use LLM for extraction" in recovered.key_decisions

    def test_from_system_message_non_state_returns_none(self):
        msg = {"role": "system", "content": "You are a helpful assistant."}
        assert SessionState.from_system_message(msg) is None


# ──────────────────────────────────────────────────────────────────────────────
# Heuristic file extraction
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractFilesHeuristic:
    def test_extracts_python_files(self):
        messages = [
            {"role": "assistant", "content": "I modified hello_agents/agent.py and added tests."},
            {"role": "tool", "tool_call_id": "c1", "content": "Wrote to tests/test_foo.py"},
        ]
        files = extract_files_heuristic(messages)
        assert any("agent.py" in f for f in files)
        assert any("test_foo.py" in f for f in files)

    def test_ignores_system_and_user_messages(self):
        messages = [
            {"role": "system", "content": "Your goal: modify config.py"},
            {"role": "user", "content": "Please change utils.py"},
        ]
        files = extract_files_heuristic(messages)
        assert files == []

    def test_extracts_multiple_extensions(self):
        messages = [
            {
                "role": "assistant",
                "content": "Updated config.yaml, README.md, and src/main.go",
            }
        ]
        files = extract_files_heuristic(messages)
        assert any("config.yaml" in f for f in files)
        assert any("README.md" in f for f in files)
        assert any("main.go" in f for f in files)

    def test_deduplicates_same_file(self):
        messages = [
            {"role": "assistant", "content": "Edited agent.py"},
            {"role": "tool", "tool_call_id": "c1", "content": "agent.py updated"},
        ]
        files = extract_files_heuristic(messages)
        assert files.count("agent.py") <= 1

    def test_empty_messages(self):
        assert extract_files_heuristic([]) == []


# ──────────────────────────────────────────────────────────────────────────────
# find_existing_state
# ──────────────────────────────────────────────────────────────────────────────

class TestFindExistingState:
    def test_finds_state_in_system_message(self):
        state = SessionState(current_goal="original goal", done_actions=["step 1"])
        messages = [
            {"role": "system", "content": "regular system"},
            state.as_system_message(),
            {"role": "user", "content": "hello"},
        ]
        found = find_existing_state(messages)
        assert found is not None
        assert found.current_goal == "original goal"

    def test_returns_none_when_no_state(self):
        messages = [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "hello"},
        ]
        assert find_existing_state(messages) is None

    def test_empty_messages(self):
        assert find_existing_state([]) is None


# ──────────────────────────────────────────────────────────────────────────────
# inject_state_into_messages
# ──────────────────────────────────────────────────────────────────────────────

class TestInjectStateIntoMessages:
    def test_injects_after_first_system_message(self):
        state = SessionState(current_goal="inject test")
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = inject_state_into_messages(messages, state)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "sys"  # original system first
        assert result[1]["role"] == "system"
        assert "[会话状态]" in result[1]["content"]

    def test_replaces_existing_state_message(self):
        old_state = SessionState(current_goal="old goal")
        new_state = SessionState(current_goal="new goal")
        messages = [
            {"role": "system", "content": "sys"},
            old_state.as_system_message(),
            {"role": "user", "content": "hi"},
        ]
        result = inject_state_into_messages(messages, new_state)
        state_msgs = [m for m in result if "[会话状态]" in m.get("content", "")]
        assert len(state_msgs) == 1
        assert "new goal" in state_msgs[0]["content"]

    def test_empty_state_not_injected(self):
        state = SessionState()  # empty
        messages = [{"role": "user", "content": "hi"}]
        result = inject_state_into_messages(messages, state)
        assert result == messages

    def test_prepends_when_no_system_message(self):
        state = SessionState(current_goal="goal")
        messages = [{"role": "user", "content": "hi"}]
        result = inject_state_into_messages(messages, state, after_system=False)
        assert result[0]["role"] == "system"
        assert "[会话状态]" in result[0]["content"]


# ──────────────────────────────────────────────────────────────────────────────
# extract_session_state (async, mocked LLM)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_session_state_calls_llm():
    messages = [
        {"role": "user", "content": "please implement the login feature"},
        {"role": "assistant", "content": "I modified hello_agents/auth.py to add login"},
        {"role": "tool", "tool_call_id": "c1", "content": "auth.py written successfully"},
    ]

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json_response = """{
        "current_goal": "implement login feature",
        "done_actions": ["modified auth.py"],
        "changed_files": ["hello_agents/auth.py"],
        "pending_items": ["write tests"],
        "key_decisions": ["use JWT tokens"]
    }"""

    with patch("hello_agents.context.session_state.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        state = await extract_session_state(messages)

    assert state.current_goal == "implement login feature"
    assert "modified auth.py" in state.done_actions
    assert "write tests" in state.pending_items
    assert "use JWT tokens" in state.key_decisions
    # heuristic file detection should also find auth.py
    assert any("auth.py" in f for f in state.changed_files)


@pytest.mark.asyncio
async def test_extract_session_state_merges_with_existing():
    messages = [
        {"role": "assistant", "content": "updated config.py"},
    ]
    existing = SessionState(
        current_goal="old goal",
        key_decisions=["decision from before"],
    )

    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"current_goal": "new goal", "done_actions": [], "changed_files": [], "pending_items": [], "key_decisions": []}'

    with patch("hello_agents.context.session_state.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        state = await extract_session_state(messages, existing_state=existing)

    assert state.current_goal == "new goal"
    assert "decision from before" in state.key_decisions


@pytest.mark.asyncio
async def test_extract_session_state_fallback_on_llm_error():
    messages = [
        {"role": "assistant", "content": "I edited utils.py and helper.py"},
    ]

    with patch("hello_agents.context.session_state.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_cls.return_value = mock_client

        state = await extract_session_state(messages)

    # LLM failed, but heuristic file detection still works
    assert any("utils.py" in f or "helper.py" in f for f in state.changed_files)


# ──────────────────────────────────────────────────────────────────────────────
# Integration with compress.apply_all_layers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_all_layers_with_session_state(tmp_path, monkeypatch):
    """Layer 3 + track_session_state=True injects [会话状态] into compressed output."""
    from hello_agents.context.compress import apply_all_layers

    monkeypatch.setattr("hello_agents.context.compress._SPILL_DIR", tmp_path / "s")

    msgs = [{"role": "system", "content": "You are an agent."}]
    for i in range(20):
        msgs.append({"role": "user", "content": f"question {i}: " + "X" * 200})
        msgs.append({"role": "assistant", "content": f"answer {i}: " + "Y" * 200})

    mock_summary = MagicMock()
    mock_summary.choices[0].message.content = "历史摘要"

    mock_state = MagicMock()
    mock_state.choices[0].message.content = '{"current_goal":"fix bug","done_actions":[],"changed_files":[],"pending_items":[],"key_decisions":[]}'

    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        prompt_content = kwargs["messages"][0]["content"]
        if "current_goal" in prompt_content or "会话状态" in prompt_content or "结构化" in prompt_content:
            return mock_state
        return mock_summary

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls1, \
         patch("hello_agents.context.session_state.openai.OpenAI") as mock_cls2:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = fake_create
        mock_cls1.return_value = mock_client
        mock_cls2.return_value = mock_client

        result = await apply_all_layers(
            msgs,
            history_threshold=1000,
            track_session_state=True,
        )

    # Should have a [会话状态] system message
    state_msgs = [m for m in result if "[会话状态]" in m.get("content", "")]
    assert len(state_msgs) >= 1
    assert "fix bug" in state_msgs[0]["content"]


@pytest.mark.asyncio
async def test_apply_all_layers_without_session_state_no_injection(tmp_path, monkeypatch):
    """Without track_session_state, no [会话状态] message is injected."""
    from hello_agents.context.compress import apply_all_layers

    monkeypatch.setattr("hello_agents.context.compress._SPILL_DIR", tmp_path / "s")

    msgs = [{"role": "system", "content": "sys"}]
    for i in range(20):
        msgs.append({"role": "user", "content": "q" * 200})
        msgs.append({"role": "assistant", "content": "a" * 200})

    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "摘要"

    with patch("hello_agents.context.compress.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        result = await apply_all_layers(msgs, history_threshold=1000, track_session_state=False)

    state_msgs = [m for m in result if "[会话状态]" in m.get("content", "")]
    assert len(state_msgs) == 0
