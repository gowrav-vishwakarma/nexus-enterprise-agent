"""Tests for Runtime Context Summarization (RCS) core modules."""

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.context.rcs_injector import RCSSystemPromptInjector
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord, ContextUpdate
from nexus.tools.interceptor import ContextUpdateInterceptor


def test_system_prompt_injector():
    """Test that the RCS protocol block is correctly appended to system prompt."""
    rcs_config = RuntimeContextSummarizerConfig(enabled=True)
    
    # Non-empty system message
    prompt = RCSSystemPromptInjector.inject("You are an assistant.", rcs_config)
    assert "You are an assistant." in prompt
    assert "## Context Management Protocol" in prompt

    # Empty system message
    prompt_empty = RCSSystemPromptInjector.inject("", rcs_config)
    assert "## Context Management Protocol" in prompt_empty


@pytest.mark.asyncio
async def test_context_update_interceptor():
    """Test extracting _context_updates, validation, and storage saving."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="test-agent", session_id="sess-1")

    # Add a mock tool call record that we will try to summarize
    tc_record = ToolCallRecord(
        tc_id="TC1",
        tc_index=1,
        tool_name="web_search",
        raw_response="Very large search output",
        tokens_raw=100,
    )
    turn = TurnRecord(
        turn_index=0,
        tool_calls=[tc_record],
    )
    await manager.append_turn("sess-1", turn)
    # Reload session state
    session = await manager.load_session("sess-1")

    interceptor = ContextUpdateInterceptor()
    rcs_config = RuntimeContextSummarizerConfig(enabled=True)

    # 1. Successful summary intercept
    tool_input = {
        "query": "something",
        "_context_updates": [
            {"tc_id": "TC1", "summary": "Search summary"}
        ]
    }
    
    cleaned_args, updates = await interceptor.intercept(
        tool_name="web_search",
        tool_input=tool_input,
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs_config,
    )

    assert "_context_updates" not in cleaned_args
    assert cleaned_args == {"query": "something"}
    assert len(updates) == 1
    assert updates[0].tc_id == "TC1"
    assert updates[0].summary == "Search summary"

    # Verify storage updated
    session = await manager.load_session("sess-1")
    target_tc = session.turns[0].tool_calls[0]
    assert target_tc.summarized_response == "Search summary"
    assert target_tc.summarized_by_turn == 1
    assert target_tc.is_dropped is False

    # 2. Validation: cross-session / invalid TC ID reference ignored
    tool_input_invalid = {
        "_context_updates": [
            {"tc_id": "TC_INVALID", "summary": "should be ignored"}
        ]
    }
    cleaned_args2, updates2 = await interceptor.intercept(
        tool_name="web_search",
        tool_input=tool_input_invalid,
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs_config,
    )
    assert len(updates2) == 0


def test_context_window_builder():
    """Test message formatting cases (unsummarized tag, summarized plain, omitted dropped)."""
    manager = SessionManager()
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="test-agent",
        llm=llm_config,
        rcs=RuntimeContextSummarizerConfig(enabled=True)
    )

    builder = ContextWindowBuilder()

    # Create dummy session
    session = AgentSession(session_id="sess-1", agent_id="test-agent")

    # Add tool calls representing Case 1, 2, and 3
    # Case 1: Unsummarized
    tc_unsummarized = ToolCallRecord(
        tc_id="TC1",
        tc_index=1,
        tool_name="tool_a",
        tool_input={"x": 10},
        raw_response="Unsummarized raw result",
    )
    # Case 2: Summarized
    tc_summarized = ToolCallRecord(
        tc_id="TC2",
        tc_index=2,
        tool_name="tool_b",
        tool_input={},
        raw_response="Original response...",
        summarized_response="Short summary",
    )
    # Case 3: Dropped
    tc_dropped = ToolCallRecord(
        tc_id="TC3",
        tc_index=3,
        tool_name="tool_c",
        tool_input={},
        raw_response="Verbose error trace...",
        summarized_response="[]",
        is_dropped=True,
    )

    turn = TurnRecord(
        turn_index=0,
        user_message="Find details",
        llm_messages=[{"role": "assistant", "content": "Let me run tools"}],
        tool_calls=[tc_unsummarized, tc_summarized, tc_dropped],
    )
    session.turns.append(turn)

    messages = builder.build(session, agent_config, current_user_message="Next question")

    # 1. System prompt + user/assistant messages present
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Find details"

    # 2. Verify rendering of Case 1: Unsummarized tag
    tool_messages = [m for m in messages if m["role"] == "tool"]
    # TC1 and TC2 should yield messages, TC3 (dropped) should be omitted
    assert len(tool_messages) == 2

    # Case 1 rendering: [TC1] tool_a(x=10)\nUnsummarized raw result
    assert "[TC1] tool_a(x=10)" in tool_messages[0]["content"]
    assert "Unsummarized raw result" in tool_messages[0]["content"]

    # Case 2 rendering: tool_b result: Short summary
    assert tool_messages[1]["content"] == "tool_b result: Short summary"
    assert "[TC2]" not in tool_messages[1]["content"]
