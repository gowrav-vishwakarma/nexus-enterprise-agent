"""Tests for Runtime Context Summarization (RCS) core modules."""

import pytest

from nexus.config import AgentConfig, LLMProviderConfig, DEFAULT_RCS_SYSTEM_BLOCK
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.context.rcs_injector import RCSSystemPromptInjector
from nexus.llm.content_tool_calls import EMPTY_ASSISTANT_PLACEHOLDER
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
    """Test message formatting: unsummarized keeps its tag, summarized loses it, and a
    legacy "[]" summary falls back to the full raw response."""
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

    # Case 1: Not summarized
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
    # Legacy "[]" sentinel written by an older version: counts as NOT summarized
    tc_legacy_sentinel = ToolCallRecord(
        tc_id="TC3",
        tc_index=3,
        tool_name="tool_c",
        tool_input={},
        raw_response="Verbose error trace...",
        summarized_response="[]",
    )

    turn = TurnRecord(
        turn_index=0,
        user_message="Find details",
        llm_messages=[{"role": "assistant", "content": "Let me run tools"}],
        tool_calls=[tc_unsummarized, tc_summarized, tc_legacy_sentinel],
    )
    session.turns.append(turn)

    messages = await builder.build(session, agent_config, current_user_message="Next question")

    # 1. System prompt + user/assistant messages present
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Find details"

    # 2. Every tool call yields a tool message — nothing is ever omitted
    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert len(tool_messages) == 3

    # Case 1 rendering: [TC1] tool_a(x=10)\nUnsummarized raw result
    assert "[TC1] tool_a(x=10)" in tool_messages[0]["content"]
    assert "Unsummarized raw result" in tool_messages[0]["content"]

    # Case 2 rendering: tool_b()\nShort summary (signature kept, [TCn] tag dropped)
    assert tool_messages[1]["content"] == "tool_b()\nShort summary"
    assert "[TC2]" not in tool_messages[1]["content"]

    # Legacy "[]" renders the full raw response, tagged so it can be summarized later
    assert "[TC3] tool_c()" in tool_messages[2]["content"]
    assert "Verbose error trace..." in tool_messages[2]["content"]


# =============================================================================
# Interceptor: additional coverage
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update_item",
    [
        {"tc_id": "TC1", "summary": "[]"},
        {"tc_id": "TC1", "summary": ""},
        {"tc_id": "TC1", "summary": "   "},
        {"tc_id": "TC1", "summary": None},
        {"tc_id": "TC1"},
    ],
    ids=["sentinel", "empty", "whitespace", "null", "missing"],
)
async def test_interceptor_no_summary_leaves_tc_untouched(update_item):
    """Every spelling of "no summary" is a no-op: the TC stays raw, never dropped."""
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="nosum-sess")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", raw_response="big", tokens_raw=100)
    await manager.append_turn("nosum-sess", TurnRecord(turn_index=0, tool_calls=[tc]))
    session = await manager.load_session("nosum-sess")

    interceptor = ContextUpdateInterceptor()
    rcs = RuntimeContextSummarizerConfig(enabled=True)

    cleaned, updates = await interceptor.intercept(
        tool_name="t",
        tool_input={"_context_updates": [update_item]},
        session=session,
        current_turn_index=1,
        storage_adapter=manager,
        rcs_config=rcs,
    )
    assert cleaned == {}
    assert updates == []

    session = await manager.load_session("nosum-sess")
    target = session.turns[0].tool_calls[0]
    assert target.summarized_response is None
    assert target.tokens_summarized is None


@pytest.mark.asyncio
async def test_builder_renders_raw_when_summary_is_empty():
    """A stored empty summary must not blank out the result."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="test-agent", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True)
    )
    session = AgentSession(session_id="empty-sum", agent_id="test-agent")
    session.turns.append(
        TurnRecord(
            turn_index=0,
            user_message="go",
            llm_messages=[{"role": "assistant", "content": "running"}],
            tool_calls=[
                ToolCallRecord(
                    tc_id="TC1",
                    tc_index=1,
                    tool_name="tool_a",
                    tool_input={},
                    raw_response="THE REAL RESULT",
                    summarized_response="",
                )
            ],
        )
    )

    messages = await ContextWindowBuilder().build(session, agent_config)

    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "THE REAL RESULT" in tool_messages[0]["content"]
    assert "[TC1] tool_a()" in tool_messages[0]["content"]


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
    """compact() summarizes oldest unsummarized TCs and persists them. A TC whose
    summary comes back unusable keeps its raw result instead of being discarded."""
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
        LLMResponse(content="", usage=TokenUsage(), finish_reason="stop", raw_response={}),
    ])
    compactor = ServerCompactor(config=cfg, llm_proxy=llm, storage_adapter=manager)

    result = await compactor.compact(session, current_turn_index=1)

    # Only the TC with a usable summary is compacted; the other is left alone.
    assert result["tcs_compacted"] == ["TC1"]
    assert result["tokens_saved"] > 0
    assert session.total_tokens_saved_by_rcs == result["tokens_saved"]

    session = await manager.load_session("compact-sess")
    tcs = session.turns[0].tool_calls
    assert tcs[0].summarized_response == "summary1"
    assert tcs[1].summarized_response is None


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
async def test_builder_keeps_assistant_tool_calls_answered():
    """Assistant tool_calls are always kept and always answered by a tool message.

    Legacy sessions stored a "[]" summary to mean "dropped". Those must now replay
    intact rather than having the tool_call stripped out of the assistant message.
    """
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(tc_id="TC1", tc_index=1, tool_name="t", tool_input={}, raw_response="r", summarized_response="[]")
    session.turns.append(TurnRecord(
        turn_index=0,
        user_message="hi",
        llm_messages=[{"role": "assistant", "content": None, "tool_calls": [{"id": "TC1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}],
        tool_calls=[tc],
    ))
    messages = await builder.build(session, agent_config, current_user_message="next")

    requested_ids = {
        c["id"]
        for m in messages
        if m["role"] == "assistant"
        for c in (m.get("tool_calls") or [])
    }
    answered_ids = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert requested_ids == {"TC1"}
    assert requested_ids == answered_ids


@pytest.mark.asyncio
async def test_builder_never_has_consecutive_assistant_messages():
    """Several summarized tool turns in a row must not leave adjacent assistants."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    for i in range(3):
        session.turns.append(TurnRecord(
            turn_index=i,
            user_message="hi" if i == 0 else None,
            llm_messages=[{
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"call-{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            }],
            tool_calls=[ToolCallRecord(
                tc_id=f"TC{i}", tc_index=i, tool_name="t", tool_input={},
                raw_response="r" * 200, call_id=f"call-{i}", summarized_response="[]",
            )],
        ))

    messages = await builder.build(session, agent_config, current_user_message="next")

    roles = [m["role"] for m in messages]
    assert not any(
        roles[i] == "assistant" and roles[i + 1] == "assistant" for i in range(len(roles) - 1)
    )
    assert messages[-1]["role"] == "user"
    assert not any(EMPTY_ASSISTANT_PLACEHOLDER in (m.get("content") or "") for m in messages)


def test_coalesce_consecutive_assistants_merges_text_only():
    """Adjacent plain assistants merge; a tool_calls-bearing assistant never does."""
    coalesce = ContextWindowBuilder._coalesce_consecutive_assistants

    merged = coalesce([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "first"},
        {"role": "assistant", "content": "second"},
    ])
    assert [m["role"] for m in merged] == ["user", "assistant"]
    assert merged[-1]["content"] == "first\n\nsecond"

    tool_call = {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    untouched = coalesce([
        {"role": "assistant", "content": "text", "tool_calls": [tool_call]},
        {"role": "tool", "tool_call_id": "c1", "content": "res"},
        {"role": "assistant", "content": "after"},
    ])
    assert len(untouched) == 3
    assert untouched[0]["tool_calls"] == [tool_call]


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
            {"tc_id": "TC2", "summary": "s2"},
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
    """No summarized TCs → zero recurring savings."""
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
async def test_count_rcs_savings_zero_for_legacy_sentinel():
    """A legacy "[]" summary is not a summary, so it yields no savings — its full
    raw response is back in context."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(name="a", llm=llm_config, rcs=RuntimeContextSummarizerConfig(enabled=True))
    builder = ContextWindowBuilder()
    session = AgentSession(session_id="s", agent_id="a")
    tc = ToolCallRecord(
        tc_id="TC1", tc_index=1, tool_name="t", tool_input={"q": "x"},
        raw_response="A" * 500, call_id="call-1", summarized_response="[]",
    )
    session.turns.append(TurnRecord(
        turn_index=0, user_message="hi",
        llm_messages=[{"role": "assistant", "content": "ok", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}],
        tool_calls=[tc],
    ))
    messages = await builder.build(session, agent_config, current_user_message="next")
    savings = builder.count_rcs_savings(messages, session, agent_config)
    assert savings == 0


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
