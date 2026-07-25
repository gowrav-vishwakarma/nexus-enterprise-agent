"""Tests for Runtime Context Summarization (RCS) core modules."""

import pytest

from nexus.config import AgentConfig, LLMProviderConfig, DEFAULT_RCS_SYSTEM_BLOCK
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
    assert DEFAULT_RCS_SYSTEM_BLOCK.strip() in prompt

    # Empty system message
    prompt_empty = RCSSystemPromptInjector.inject("", rcs_config)
    assert DEFAULT_RCS_SYSTEM_BLOCK.strip() in prompt_empty


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


@pytest.mark.asyncio
async def test_context_window_builder():
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

    messages = await builder.build(session, agent_config, current_user_message="Next question")

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

    # Case 2 rendering: tool_b()\nShort summary (signature kept, [TCn] tag dropped)
    assert tool_messages[1]["content"] == "tool_b()\nShort summary"
    assert "[TC2]" not in tool_messages[1]["content"]


# =============================================================================
# Interceptor: additional coverage
# =============================================================================

@pytest.mark.asyncio
async def test_interceptor_empty_sentinel_drops_tc():
    """summary == '[]' marks the TC as dropped and zero summarized tokens."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="drop-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="big", tokens_raw=100)
    await manager.append_turn("drop-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("drop-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    cleaned, updates = await interceptor.intercept(
        tool_name="t",
        tool_input={"_context_updates": [{"tc_id": "TC1", "summary": "[]"}]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    assert cleaned == {}
    assert len(updates) == 1
    assert updates[0].tokens_saved == 100  # full raw saved when dropped

    session = await manager.load_session("drop-sess")
    target = session.turns[0].tool_calls[0]
    assert target.is_dropped is True
    assert target.tokens_summarized == 0


@pytest.mark.asyncio
async def test_interceptor_multiple_updates_in_one_call():
    """Multiple TCs summarized in a single _context_updates list."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="multi-sess")
    tc1 = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t1", raw_response="r1", tokens_raw=100)
    tc2 = ToolCallRecord(tc_id="TC2", tc_index=2, tool_name="t2", raw_response="r2", tokens_raw=200)
    await manager.append_turn("multi-sess", TurnRecord(turn_index=0, tool_calls=[tc1, tc2]))
    session = await manager.load_session("multi-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    cleaned, updates = await interceptor.intercept(
        tool_name="t1",
        tool_input={"_context_updates": [
            {"tc_id": "TC1", "summary": "s1"},
            {"tc_id": "TC2", "summary": "s2"},
        ]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    assert len(updates) == 2
    assert {u.tc_id for u in updates} == {"TC1", "TC2"}
    assert session.total_tokens_saved_by_rcs > 0


@pytest.mark.asyncio
async def test_interceptor_custom_param_name():
    """Interceptor honours a custom context_updates_param_name."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="custom-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="r", tokens_raw=50)
    await manager.append_turn("custom-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("custom-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True, context_updates_param_name="_my_updates")

    cleaned, updates = await interceptor.intercept(
        tool_name="t",
        tool_input={"_my_updates": [{"tc_id": "TC1", "summary": "ok"}]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    assert "_my_updates" not in cleaned
    assert len(updates) == 1


@pytest.mark.asyncio
async def test_interceptor_disabled_is_noop():
    """When RCS is disabled the interceptor returns args unchanged and no updates."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="noop-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="r", tokens_raw=50)
    await manager.append_turn("noop-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("noop-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=False)

    cleaned, updates = await interceptor.intercept(
        tool_name="t",
        tool_input={"query": "q", "_context_updates": [{"tc_id": "TC1", "summary": "s"}]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    # RCS disabled: _context_updates is NOT stripped (transparent passthrough)
    assert cleaned == {"query": "q", "_context_updates": [{"tc_id": "TC1", "summary": "s"}]}
    assert updates == []


@pytest.mark.asyncio
async def test_interceptor_emits_cross_session_event_on_invalid_tc():
    """Invalid tc_id emits RCS_CROSS_SESSION_TC_REFERENCE via the emitter."""
    from nexus.events.emitter import NexusEventEmitter
    from nexus.events.models import NexusEventType

    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="xref-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="r", tokens_raw=50)
    await manager.append_turn("xref-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("xref-sess")

    emitted: list = []
    emitter = NexusEventEmitter()

    class _Sink:
        async def emit(self, event):
            emitted.append(event)

        async def flush(self):
            pass

    emitter.register_sink(_Sink())
    interceptor = ContextUpdateInterceptor(event_emitter=emitter)
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    await interceptor.intercept(
        tool_name="t",
        tool_input={"_context_updates": [{"tc_id": "TC_BOGUS", "summary": "x"}]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    types = [e.event_type for e in emitted]
    assert NexusEventType.RCS_CROSS_SESSION_TC_REFERENCE in types


@pytest.mark.asyncio
async def test_interceptor_re_summarization_uses_marginal_savings():
    """Re-summarizing an already-summarized TC counts only marginal savings."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="resum-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="r" * 500, tokens_raw=200)
    await manager.append_turn("resum-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("resum-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    # First summarization
    _, updates1 = await interceptor.intercept(
        tool_name="t",
        tool_input={"_context_updates": [{"tc_id": "TC1", "summary": "short"}]},
        session=session, current_turn_index=1, storage_adapter=manager, rcs_config=rcs,
    )
    saved1 = updates1[0].tokens_saved
    total1 = session.total_tokens_saved_by_rcs

    # Re-summarize with a slightly different summary
    _, updates2 = await interceptor.intercept(
        tool_name="t",
        tool_input={"_context_updates": [{"tc_id": "TC1", "summary": "shorter"}]},
        session=session, current_turn_index=2, storage_adapter=manager, rcs_config=rcs,
    )
    saved2 = updates2[0].tokens_saved
    total2 = session.total_tokens_saved_by_rcs

    # Marginal savings only — no double-counting from tokens_raw
    assert total2 == total1 + saved2
    assert saved2 < saved1  # re-summarization saves less than the first pass


# =============================================================================
# ServerCompactor
# =============================================================================

@pytest.mark.asyncio
async def test_compactor_should_trigger_thresholds():
    """should_trigger respects threshold and presence of unsummarized TCs."""
    from nexus.rcs.compactor import ServerCompactor
    from unittest.mock import MagicMock

    cfg = ServerCompactorConfig(enabled=True, trigger_token_threshold=1000)
    compactor = ServerCompactor(config=cfg, llm_proxy=MagicMock(), storage_adapter=MagicMock())

    session = AgentSession(session_id="s", agent_id="a")
    # No TCs → False even over threshold
    assert await compactor.should_trigger(session, 2000) is False

    # Unsummarized TC but below threshold → False
    session.turns.append(TurnRecord(turn_index=0, tool_calls=[
        ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="r", tokens_raw=100),
    ]))
    assert await compactor.should_trigger(session, 500) is False

    # Over threshold with unsummarized TC → True
    assert await compactor.should_trigger(session, 2000) is True

    # All summarized → False
    session.turns[0].tool_calls[0].summarized_response = "done"
    assert await compactor.should_trigger(session, 2000) is False


@pytest.mark.asyncio
async def test_compactor_compact_with_mocked_llm():
    """compact() summarizes oldest unsummarized TCs, sets is_dropped for [], persists."""
    from nexus.rcs.compactor import ServerCompactor
    from nexus.llm.response import LLMResponse, TokenUsage
    from unittest.mock import AsyncMock, MagicMock

    cfg = ServerCompactorConfig(enabled=True, trigger_token_threshold=100, compact_oldest_n_tcs=2)
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="compact-sess")
    tc1 = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t1", raw_response="big1", tokens_raw=500)
    tc2 = ToolCallRecord(tc_id="TC2", tc_index=2, tool_name="t2", raw_response="big2", tokens_raw=500)
    await manager.append_turn("compact-sess", TurnRecord(turn_index=0, tool_calls=[tc1, tc2]))
    session = await manager.load_session("compact-sess")

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=[
        LLMResponse(content="summary1", usage=TokenUsage(), finish_reason="stop", raw_response={}),
        LLMResponse(content="[]", usage=TokenUsage(), finish_reason="stop", raw_response={}),
    ])
    compactor = ServerCompactor(config=cfg, llm_proxy=llm, storage_adapter=manager)

    result = await compactor.compact(session, current_turn_index=1)

    assert len(result["tcs_compacted"]) == 2
    assert result["tokens_saved"] > 0
    assert session.total_tokens_saved_by_rcs == result["tokens_saved"]

    session = await manager.load_session("compact-sess")
    tcs = session.turns[0].tool_calls
    assert tcs[0].summarized_response == "summary1"
    assert tcs[0].is_dropped is False
    assert tcs[1].summarized_response == "[]"
    assert tcs[1].is_dropped is True


# =============================================================================
# Builder: additional coverage
# =============================================================================

@pytest.mark.asyncio
async def test_builder_rcs_disabled_no_tag():
    """RCS disabled: tool messages show raw response with no [TCn] tag."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=False))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="tool_a", tool_input={"x": 1}, raw_response="raw result")
    session.turns.append(TurnRecord(turn_index=0, user_message="hi", tool_calls=[tc]))
    messages = await builder.build(session, agent_config, current_user_message="next")
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "[TC1]" not in tool_msgs[0]["content"]
    assert tool_msgs[0]["content"] == "raw result"


@pytest.mark.asyncio
async def test_builder_custom_tag_format():
    """Custom tc_tag_format is honoured for unsummarized TCs."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    rcs = RuntimeContextSummarizerConfig(enabled=True, tc_tag_format="<TC_{n}>")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=rcs)
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"}, raw_response="raw")
    session.turns.append(TurnRecord(turn_index=0, user_message="hi", tool_calls=[tc]))
    messages = await builder.build(session, agent_config, current_user_message="next")
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert "<TC_1>" in tool_msgs[0]["content"]
    assert "[TC1]" not in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_builder_all_dropped_tool_calls_filtered_from_assistant():
    """When all tool_calls in a turn are dropped, the assistant message is filtered."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", tool_input={}, raw_response="r", summarized_response="[]", is_dropped=True)
    session.turns.append(TurnRecord(
        turn_index=0,
        user_message="hi",
        llm_messages=[{"role": "assistant", "content": None, "tool_calls": [{"id": "TC1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}],
        tool_calls=[tc],
    ))
    messages = await builder.build(session, agent_config, current_user_message="next")
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    # The dropped tool_call should be filtered from the assistant message
    for m in assistant_msgs:
        if m.get("tool_calls"):
            assert all(tc_call.get("id") != "TC1" for tc_call in m["tool_calls"])


@pytest.mark.asyncio
async def test_builder_summarized_keeps_signature_no_tag():
    """Summarized TC: signature present, [TCn] tag absent (bug #5 fix)."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(
        tc_id="TC1", tc_index=1, tool_name="search", tool_input={"query": "quantum"},
        raw_response="huge blob", summarized_response="found section 4.2",
    )
    session.turns.append(TurnRecord(turn_index=0, user_message="hi", tool_calls=[tc]))
    messages = await builder.build(session, agent_config, current_user_message="next")
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    content = tool_msgs[0]["content"]
    assert "[TC1]" not in content          # no tag → no re-summarization
    assert "search(query" in content       # signature kept
    assert "found section 4.2" in content  # summary is the response


@pytest.mark.asyncio
async def test_token_accounting_consistency():
    """turn.tokens_saved_this_turn == sum(per-update savings) == delta to session counter."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="acct-sess")
    tc1 = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t1", raw_response="r" * 400, tokens_raw=200)
    tc2 = ToolCallRecord(tc_id="TC2", tc_index=2, tool_name="t2", raw_response="r" * 400, tokens_raw=200)
    await manager.append_turn("acct-sess", TurnRecord(turn_index=0, tool_calls=[tc1, tc2]))
    session = await manager.load_session("acct-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    before = session.total_tokens_saved_by_rcs
    _, updates = await interceptor.intercept(
        tool_name="t1",
        tool_input={"_context_updates": [
            {"tc_id": "TC1", "summary": "s1"},
            {"tc_id": "TC2", "summary": "[]"},
        ]},
        session=session, current_turn_index=1, storage_adapter=manager, rcs_config=rcs,
    )
    after = session.total_tokens_saved_by_rcs
    per_update_sum = sum(u.tokens_saved for u in updates)
    assert per_update_sum == after - before
    assert per_update_sum > 0


# =============================================================================
# count_rcs_savings — recurring input-token savings
# =============================================================================

@pytest.mark.asyncio
async def test_count_rcs_savings_zero_when_nothing_summarized():
    """No summarized/dropped TCs → zero recurring savings."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"}, raw_response="raw", call_id="call-1")
    session.turns.append(TurnRecord(turn_index=0, user_message="hi", tool_calls=[tc]))
    messages = await builder.build(session, agent_config, current_user_message="next")
    savings = builder.count_rcs_savings(messages, session, agent_config)
    assert savings == 0


@pytest.mark.asyncio
async def test_count_rcs_savings_positive_when_summarized():
    """Summarized TC in context → positive recurring savings."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(
        tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"},
        raw_response="A" * 500, call_id="call-1", summarized_response="short",
    )
    session.turns.append(TurnRecord(
        turn_index=0, user_message="hi",
        llm_messages=[{"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}],
        tool_calls=[tc],
    ))
    messages = await builder.build(session, agent_config, current_user_message="next")
    savings = builder.count_rcs_savings(messages, session, agent_config)
    assert savings > 0


@pytest.mark.asyncio
async def test_count_rcs_savings_dropped_tc():
    """Dropped TC that would have been in context → full raw tokens as savings."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(
        tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"},
        raw_response="A" * 500, call_id="call-1", summarized_response="[]", is_dropped=True,
    )
    session.turns.append(TurnRecord(
        turn_index=0, user_message="hi",
        llm_messages=[{"role": "assistant", "content": "ok", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}],
        tool_calls=[tc],
    ))
    messages = await builder.build(session, agent_config, current_user_message="next")
    savings = builder.count_rcs_savings(messages, session, agent_config)
    # Dropped TC's full raw rendering is the savings
    assert savings > 0


@pytest.mark.asyncio
async def test_count_rcs_savings_disabled_returns_zero():
    """RCS disabled → count_rcs_savings returns 0."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=False))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(
        tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"},
        raw_response="raw", call_id="call-1", summarized_response="short",
    )
    session.turns.append(TurnRecord(turn_index=0, user_message="hi", tool_calls=[tc]))
    messages = await builder.build(session, agent_config, current_user_message="next")
    savings = builder.count_rcs_savings(messages, session, agent_config)
    assert savings == 0


def test_token_usage_aggregate_and_round_trip():
    """AgentSession.token_usage aggregates per-turn tokens + RCS counters and
    is included verbatim in model_dump(mode='json') for external analysis."""
    session = AgentSession(session_id="s", agent_id="a")
    session.rcs_enabled = True
    session.total_tokens_saved_by_rcs = 100
    session.cumulative_input_tokens_saved_by_rcs = 250
    session.turns.append(TurnRecord(
        turn_index=0, user_message="hi",
        total_tokens_in=120, total_tokens_out=30,
    ))
    session.turns.append(TurnRecord(
        turn_index=1, user_message="again",
        total_tokens_in=200, total_tokens_out=45,
    ))

    usage = session.token_usage
    assert usage == {
        "total_tokens_in": 320,
        "total_tokens_out": 75,
        "total_tokens_saved_by_rcs": 100,
        "cumulative_input_tokens_saved_by_rcs": 250,
        "rcs_enabled": True,
    }

    # Computed field is serialized into the JSON dump (source of truth for
    # external readers) but ignored on validate (recomputed from turns).
    dumped = session.model_dump(mode="json")
    assert dumped["token_usage"] == usage

    reloaded = AgentSession.model_validate(dumped)
    assert reloaded.token_usage == usage
    assert reloaded.rcs_enabled is True


def test_token_usage_defaults_when_empty():
    """Empty session → zeroed aggregate, rcs_enabled False."""
    session = AgentSession(session_id="s", agent_id="a")
    assert session.token_usage == {
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_tokens_saved_by_rcs": 0,
        "cumulative_input_tokens_saved_by_rcs": 0,
        "rcs_enabled": False,
    }
