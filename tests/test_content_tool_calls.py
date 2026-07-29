"""Tests for content-side XML tool-call extraction."""

import pytest

from nexus.llm.content_tool_calls import (
    EMPTY_ASSISTANT_PLACEHOLDER,
    build_assistant_llm_message,
    extract_tool_calls_from_text,
    promote_content_tool_calls,
    sanitize_assistant_llm_message,
)
from nexus.llm.response import LLMResponse, ToolCallRequest


def test_parse_nemotron_execute_sql_with_quoted_sql() -> None:
    text = (
        "No closing logs yet. Let me check the table:\n"
        "<tool_call>\n"
        "<function=execute_sql>\n"
        '<parameter=sql>\nSELECT 1 FROM "Accounts" WHERE id = 2\n</parameter>\n'
        "</function>\n"
        "</tool_call>"
    )
    calls, cleaned = extract_tool_calls_from_text(text)
    assert len(calls) == 1
    assert calls[0].tool_name == "execute_sql"
    assert 'SELECT 1 FROM "Accounts"' in str(calls[0].tool_input.get("sql", ""))
    assert "<tool_call>" not in (cleaned or "")
    assert "No closing logs yet" in (cleaned or "")


def test_parse_multiple_nemotron_blocks() -> None:
    text = (
        "<tool_call><function=foo><parameter=x>1</parameter></function></tool_call>"
        "<tool_call><function=bar><parameter=y>2</parameter></function></tool_call>"
    )
    calls, cleaned = extract_tool_calls_from_text(text)
    assert len(calls) == 2
    assert {c.tool_name for c in calls} == {"foo", "bar"}
    assert cleaned in (None, "")


def test_promote_from_reasoning_when_content_empty() -> None:
    reasoning = (
        "<tool_call><function=execute_sql>"
        "<parameter=sql>SELECT 1</parameter></function></tool_call>"
    )
    resp = LLMResponse(content=None, reasoning=reasoning, tool_calls=[])
    promoted = promote_content_tool_calls(resp)
    assert len(promoted.tool_calls) == 1
    assert promoted.tool_calls[0].tool_name == "execute_sql"
    assert promoted.reasoning in (None, "")


def test_sanitize_empty_assistant_for_replay() -> None:
    msg = {"role": "assistant", "content": None, "tool_calls": None}
    out = sanitize_assistant_llm_message(msg, placeholder=EMPTY_ASSISTANT_PLACEHOLDER)
    assert out["content"] == EMPTY_ASSISTANT_PLACEHOLDER
    assert "tool_calls" not in out


def test_build_assistant_llm_message_reasoning_only() -> None:
    msg = build_assistant_llm_message(content=None, tool_calls=[])
    assert msg["content"] == "(no response)"
    assert "tool_calls" not in msg


def test_build_assistant_llm_message_with_tools() -> None:
    tc = ToolCallRequest(id="call_1", tool_name="execute_sql", tool_input={"sql": "SELECT 1"})
    msg = build_assistant_llm_message(content=None, tool_calls=[tc])
    assert msg["tool_calls"][0]["id"] == "call_1"
    assert "tool_calls" in msg


@pytest.mark.asyncio
async def test_context_builder_repairs_empty_assistant_message() -> None:
    """Poisoned history (null content, no tool_calls) is fixed on replay."""
    from nexus.config import AgentConfig, LLMProviderConfig
    from nexus.context.builder import ContextWindowBuilder
    from nexus.session.models import AgentSession, TurnRecord

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(name="test-agent", llm=llm_config)
    session = AgentSession(session_id="sess-empty", agent_id="test-agent")
    session.turns.append(
        TurnRecord(
            turn_index=0,
            user_message="Hi",
            llm_messages=[{"role": "assistant", "content": None}],
            tool_calls=[],
        )
    )
    messages = await ContextWindowBuilder().build(
        session, agent_config, current_user_message="Follow up"
    )
    assistants = [m for m in messages if m.get("role") == "assistant"]
    assert assistants
    assert assistants[0]["content"] == EMPTY_ASSISTANT_PLACEHOLDER
    assert "tool_calls" not in assistants[0]
