"""RCS end-to-end integration tests (mocked + opt-in live LLM)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.agent import AgentPersonaConfig, TurnConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

NOISE_BLOB = (
    "PANDAS COOKBOOK: How to make chocolate chip cookies with butter, flour, and sugar. "
    "Season the dough with vanilla extract. Bake at 350F for 12 minutes. "
    "This recipe has nothing to do with physics, quantum mechanics, or documentation. "
) * 8

RCS_SUMMARY = "I checked noise_lookup but it does not contain what I want."

USER_PROMPT = (
    "Find quantum entanglement info in our docs. "
    "First call global.noise_lookup with query 'quantum entanglement'. "
    "If that result is not about quantum physics, call global.doc_search next and include "
    f"_context_updates summarizing the noise_lookup result as: '{RCS_SUMMARY}'"
)


@tool(name="noise_lookup", description="General lookup that may return unrelated content.")
def noise_lookup(query: str) -> str:
    return f"[noise_lookup for '{query}'] {NOISE_BLOB}"


@tool(name="doc_search", description="Search internal documentation.")
def doc_search(query: str) -> str:
    return f"Doc hit for '{query}': quantum entanglement is covered in section 4.2."


def _register_rcs_tools(registry: ToolRegistry) -> None:
    registry.register_tool(noise_lookup)
    registry.register_tool(doc_search)


def _rcs_agent_config(llm_config: LLMProviderConfig) -> AgentConfig:
    return AgentConfig(
        name="rcs-test-agent",
        llm=llm_config,
        rcs=RuntimeContextSummarizerConfig(enabled=True),
        tool_plugins=["global"],
        turns=TurnConfig(max_turns=5, turn_timeout_seconds=120),
        persona=AgentPersonaConfig(
            role="Research assistant",
            goal="Find correct documentation and manage context efficiently",
        ),
    )


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def llm_config_from_env() -> LLMProviderConfig:
    """Build LLM config from NEXUS_LLM_* or PLATFORM_OPENAI_KEY env vars."""
    _load_env()
    provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    base_url = os.getenv("NEXUS_LLM_BASE_URL", "") or None
    model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
    api_key = os.getenv("NEXUS_LLM_API_KEY") or os.getenv("PLATFORM_OPENAI_KEY", "")
    if not api_key or api_key.startswith("sk-your-"):
        pytest.skip("No LLM API key configured (set NEXUS_LLM_API_KEY or PLATFORM_OPENAI_KEY)")
    return LLMProviderConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
    )


def _summary_matches_intent(summary: str) -> bool:
    lower = summary.lower()
    return any(
        phrase in lower
        for phrase in ("checked", "not contain", "does not", "not relevant", "unrelated")
    )


async def _assert_rcs_applied(session, agent_config: AgentConfig) -> None:
    """Shared assertions for mocked and live RCS e2e runs."""
    assert len(session.turns) >= 2

    noise_tc = session.turns[0].tool_calls[0]
    assert noise_tc.tool_name == "global.noise_lookup"
    assert noise_tc.tc_id == "TC1"
    assert noise_tc.tc_index == 1
    assert "PANDAS COOKBOOK" in noise_tc.raw_response
    assert noise_tc.summarized_response is not None

    has_updates = any(turn.context_updates_received for turn in session.turns)
    assert has_updates or noise_tc.summarized_response is not None

    summary = noise_tc.summarized_response or ""
    assert _summary_matches_intent(summary), f"Unexpected summary: {summary!r}"

    for turn in session.turns[1:]:
        for tc in turn.tool_calls:
            assert "_context_updates" not in tc.tool_input

    messages = await ContextWindowBuilder().build(session, agent_config)
    tool_contents = [m["content"] for m in messages if m.get("role") == "tool"]
    assert any(RCS_SUMMARY.lower() in c.lower() or _summary_matches_intent(c) for c in tool_contents)
    assert not any("PANDAS COOKBOOK" in c for c in tool_contents)

    assert session.total_tokens_saved_by_rcs > 0


@pytest.mark.asyncio
async def test_rcs_e2e_mocked_llm():
    """Deterministic RCS pipeline: irrelevant tool result compressed on next tool call."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)

    registry = ToolRegistry()
    _register_rcs_tools(registry)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response_turn_0 = LLMResponse(
        content="Let me try the general lookup first.",
        tool_calls=[
            ToolCallRequest(
                id="call-1",
                tool_name="global.noise_lookup",
                tool_input={"query": "quantum entanglement"},
            )
        ],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        finish_reason="tool_calls",
        raw_response={},
    )

    response_turn_2 = LLMResponse(
        content="Found quantum entanglement in section 4.2.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
        finish_reason="stop",
        raw_response={},
    )

    call_count = 0

    async def dynamic_mock_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return response_turn_0
        if call_count == 2:
            sess = await manager.load_session("rcs-mock-sess")
            tc_id = sess.turns[0].tool_calls[0].tc_id
            return LLMResponse(
                content="The noise result was useless; searching docs instead.",
                tool_calls=[
                    ToolCallRequest(
                        id="call-2",
                        tool_name="global.doc_search",
                        tool_input={
                            "query": "quantum entanglement",
                            "_context_updates": [
                                {"tc_id": tc_id, "summary": RCS_SUMMARY},
                            ],
                        },
                    )
                ],
                usage=TokenUsage(prompt_tokens=20, completion_tokens=12, total_tokens=32),
                finish_reason="tool_calls",
                raw_response={},
            )
        return response_turn_2

    mock_chat = AsyncMock(side_effect=dynamic_mock_chat)

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(
            user_message=USER_PROMPT,
            session_id="rcs-mock-sess",
        )

    assert result.status == "completed"
    assert result.total_tokens_saved_by_rcs > 0

    sess = await manager.load_session("rcs-mock-sess")
    assert sess is not None
    await _assert_rcs_applied(sess, agent_config)

    assert sess.turns[1].context_updates_received
    assert sess.turns[1].context_updates_received[0]["summary"] == RCS_SUMMARY


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_rcs_e2e_live_llm():
    """Live LLM RCS test: model compresses irrelevant noise_lookup via _context_updates."""
    llm_config = llm_config_from_env()
    agent_config = _rcs_agent_config(llm_config)

    registry = ToolRegistry()
    _register_rcs_tools(registry)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    try:
        result = await runner.run(
            user_message=USER_PROMPT,
            session_id="rcs-live-sess",
        )
    except Exception as exc:
        pytest.fail(f"Live RCS run failed: {exc}")

    sess = await manager.load_session("rcs-live-sess")
    assert sess is not None

    try:
        await _assert_rcs_applied(sess, agent_config)
    except AssertionError as exc:
        debug = {
            "turns": len(sess.turns),
            "total_tokens_saved_by_rcs": sess.total_tokens_saved_by_rcs,
            "result_tokens_saved": result.total_tokens_saved_by_rcs,
            "tool_calls": [
                {
                    "turn": i,
                    "tc_id": tc.tc_id,
                    "tool_name": tc.tool_name,
                    "summarized_response": tc.summarized_response,
                }
                for i, turn in enumerate(sess.turns)
                for tc in turn.tool_calls
            ],
            "context_updates": [
                {"turn": i, "updates": turn.context_updates_received}
                for i, turn in enumerate(sess.turns)
            ],
        }
        pytest.fail(f"{exc}\nSession debug: {debug}")


# =============================================================================
# Additional integration tests (mocked LLM)
# =============================================================================

@pytest.mark.asyncio
async def test_rcs_e2e_streaming():
    """RCS works in streaming mode (run_stream)."""
    from nexus.llm.response import LLMResponse, LLMStreamChunk, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    agent_config.stream_output = True

    registry = ToolRegistry()
    _register_rcs_tools(registry)

    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    stream_turn_chunks = [
        [
            LLMStreamChunk(content="Trying noise lookup."),
            LLMStreamChunk(
                tool_calls=[{"index": 0, "id": "c1", "name": "global.noise_lookup", "arguments": '{"query": "quantum entanglement"}'}],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            ),
        ],
        [
            LLMStreamChunk(content="Noise useless; searching docs."),
            LLMStreamChunk(
                tool_calls=[{"index": 0, "id": "c2", "name": "global.doc_search", "arguments": '{"query": "quantum entanglement", "_context_updates": [{"tc_id": "TC1", "summary": "' + RCS_SUMMARY + '"}]}'}],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=12, total_tokens=32),
            ),
        ],
        [
            LLMStreamChunk(content="Found it in section 4.2."),
            LLMStreamChunk(content="", finish_reason="stop", usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40)),
        ],
    ]
    stream_call_idx = 0

    async def mock_chat_stream(*_a, **_kw):
        nonlocal stream_call_idx
        chunks = stream_turn_chunks[stream_call_idx]
        stream_call_idx += 1

        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()

    with patch.object(runner.llm_proxy, "chat_stream", mock_chat_stream):
        events = []
        async for ev in runner.run_stream(user_message=USER_PROMPT, session_id="rcs-stream-sess"):
            events.append(ev)

    assert any(e.event_type == "final_response" for e in events)
    sess = await manager.load_session("rcs-stream-sess")
    assert sess is not None
    assert sess.total_tokens_saved_by_rcs > 0


@pytest.mark.asyncio
async def test_rcs_e2e_legacy_sentinel_is_ignored():
    """LLM passes the legacy summary='[]'; it is a no-op, so the TC keeps its full
    result and stays available for a real summary later. Nothing is ever dropped."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Dropping noise, searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [{"tc_id": "TC1", "summary": "[]"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message=USER_PROMPT, session_id="rcs-drop-sess")

    sess = await manager.load_session("rcs-drop-sess")
    noise_tc = sess.turns[0].tool_calls[0]
    assert noise_tc.summarized_response is None

    # The result is still in context, tagged so it can be summarized on a later turn.
    messages = await ContextWindowBuilder().build(sess, agent_config)
    tool_contents = [m["content"] for m in messages if m.get("role") == "tool"]
    assert any("PANDAS COOKBOOK" in c for c in tool_contents)
    assert any("[TC1]" in c for c in tool_contents)

    # Every requested tool_call is answered, so no two assistants end up adjacent.
    roles = [m["role"] for m in messages]
    assert not any(
        roles[i] == "assistant" and roles[i + 1] == "assistant" for i in range(len(roles) - 1)
    )


@pytest.mark.asyncio
async def test_rcs_e2e_multiple_tc_summarized_in_one_call():
    """LLM summarizes multiple TCs in a single _context_updates list."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Two lookups.",
        tool_calls=[
            ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q1"}),
            ToolCallRequest(id="c2", tool_name="global.noise_lookup", tool_input={"query": "q2"}),
        ],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Both useless; searching docs.",
        tool_calls=[ToolCallRequest(id="c3", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [
                {"tc_id": "TC1", "summary": "noise1 not relevant"},
                {"tc_id": "TC2", "summary": "noise2 not relevant"},
            ],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-multi-sess")

    sess = await manager.load_session("rcs-multi-sess")
    assert sess.turns[1].context_updates_received
    assert len(sess.turns[1].context_updates_received) == 2
    tc1 = sess.find_tc("TC1")
    tc2 = sess.find_tc("TC2")
    assert tc1.summarized_response == "noise1 not relevant"
    assert tc2.summarized_response == "noise2 not relevant"


@pytest.mark.asyncio
async def test_rcs_e2e_custom_param_name():
    """RCS works end-to-end with a custom context_updates_param_name."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = AgentConfig(
        name="rcs-custom",
        llm=llm_config,
        rcs=RuntimeContextSummarizerConfig(enabled=True, context_updates_param_name="_my_updates"),
        tool_plugins=["global"],
        turns=TurnConfig(max_turns=5, turn_timeout_seconds=120),
        persona=AgentPersonaConfig(role="Research assistant", goal="Find docs."),
    )
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    # Verify schema injection uses the custom name
    schemas = registry.get_tool_schemas_for_llm(rcs_config=agent_config.rcs)
    assert "_my_updates" in schemas[0]["parameters"]["properties"]

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_my_updates": [{"tc_id": "TC1", "summary": "noise not relevant"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-custom-sess")

    sess = await manager.load_session("rcs-custom-sess")
    assert sess.find_tc("TC1").summarized_response == "noise not relevant"
    assert sess.total_tokens_saved_by_rcs > 0


@pytest.mark.asyncio
async def test_rcs_invariant_tool_input_never_has_context_updates():
    """_context_updates never appears in any ToolCallRecord.tool_input after a run."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [{"tc_id": "TC1", "summary": "noise not relevant"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-invariant-sess")

    sess = await manager.load_session("rcs-invariant-sess")
    for turn in sess.turns:
        for tc in turn.tool_calls:
            assert "_context_updates" not in tc.tool_input, f"{tc.tc_id} leaked _context_updates into tool_input"


@pytest.mark.asyncio
async def test_rcs_invariant_aggregated_tokens_match_turn_sum():
    """session.total_tokens_saved_by_rcs == sum(turn.tokens_saved_this_turn)."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [{"tc_id": "TC1", "summary": "noise not relevant"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-agg-sess")

    sess = await manager.load_session("rcs-agg-sess")
    turn_sum = sum(t.tokens_saved_this_turn for t in sess.turns)
    assert turn_sum == sess.total_tokens_saved_by_rcs


@pytest.mark.asyncio
async def test_rcs_e2e_fallback_compactor_triggered():
    """Fallback compactor fires when context exceeds trigger_token_threshold."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = AgentConfig(
        name="rcs-compactor",
        llm=llm_config,
        rcs=RuntimeContextSummarizerConfig(
            enabled=True,
            fallback_compactor=ServerCompactorConfig(
                enabled=True,
                trigger_token_threshold=100,  # very low → forces compaction
                compact_oldest_n_tcs=1,
            ),
        ),
        tool_plugins=["global"],
        turns=TurnConfig(max_turns=5, turn_timeout_seconds=120),
        persona=AgentPersonaConfig(role="Research assistant", goal="Find docs."),
    )
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return response_t0
        # After compactor runs, the next LLM call returns stop
        return response_t1

    # Mock the compactor's LLM call separately
    compactor_llm_response = LLMResponse(
        content="compacted noise lookup result",
        usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        finish_reason="stop", raw_response={},
    )

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-compactor-sess")

    sess = await manager.load_session("rcs-compactor-sess")
    # The compactor should have summarized TC1
    tc1 = sess.find_tc("TC1")
    assert tc1.summarized_response is not None
    assert sess.total_tokens_saved_by_rcs > 0


# =============================================================================
# Cumulative recurring savings integration tests
# =============================================================================

@pytest.mark.asyncio
async def test_rcs_cumulative_savings_exceed_one_time():
    """After a multi-turn run, cumulative recurring savings > one-time savings.

    A TC summarized in turn 1 saves input tokens in turns 2 AND 3 (recurring),
    so cumulative_input_tokens_saved_by_rcs should be at least 2x the one-time
    total_tokens_saved_by_rcs.
    """
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [{"tc_id": "TC1", "summary": "noise not relevant"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Found it. Summarizing.",
        tool_calls=[ToolCallRequest(id="c3", tool_name="global.summarize_findings", tool_input={
            "text": "found section 4.2",
            "_context_updates": [{"tc_id": "TC2", "summary": "found section 4.2"}],
        })],
        usage=TokenUsage(prompt_tokens=25, completion_tokens=10, total_tokens=35),
        finish_reason="tool_calls", raw_response={},
    )
    response_t3 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2, response_t3][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        result = await runner.run(user_message="Search q", session_id="rcs-cumulative-sess")

    sess = await manager.load_session("rcs-cumulative-sess")
    # One-time savings: TC1 summarized in turn 1, TC2 summarized in turn 2
    assert sess.total_tokens_saved_by_rcs > 0
    # Cumulative recurring savings should be strictly greater than one-time
    # because the summarized TC1 saves input tokens in turns 2 and 3 too.
    assert sess.cumulative_input_tokens_saved_by_rcs > sess.total_tokens_saved_by_rcs
    # The result should carry the cumulative metric
    assert result.cumulative_input_tokens_saved_by_rcs == sess.cumulative_input_tokens_saved_by_rcs

    # token_usage aggregate is present in the serialized chat JSON and ties out
    # to the per-turn fields + session RCS counters (source of truth for UI /
    # external analysis).
    dumped = sess.model_dump(mode="json")
    usage = dumped["token_usage"]
    assert usage["total_tokens_in"] == sum(t.total_tokens_in for t in sess.turns)
    assert usage["total_tokens_out"] == sum(t.total_tokens_out for t in sess.turns)
    assert usage["total_tokens_saved_by_rcs"] == sess.total_tokens_saved_by_rcs
    assert usage["cumulative_input_tokens_saved_by_rcs"] == sess.cumulative_input_tokens_saved_by_rcs
    assert usage["rcs_enabled"] is True
    assert sess.token_usage == usage


@pytest.mark.asyncio
async def test_rcs_recurring_savings_monotonic():
    """cumulative_input_tokens_saved_by_rcs is monotonically non-decreasing across turns."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)
    registry = ToolRegistry()
    _register_rcs_tools(registry)
    manager = SessionManager()
    runner = AgentRunner(config=agent_config, tool_registry=registry, storage_config=manager)

    response_t0 = LLMResponse(
        content="Lookup.",
        tool_calls=[ToolCallRequest(id="c1", tool_name="global.noise_lookup", tool_input={"query": "q"})],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="tool_calls", raw_response={},
    )
    response_t1 = LLMResponse(
        content="Searching docs.",
        tool_calls=[ToolCallRequest(id="c2", tool_name="global.doc_search", tool_input={
            "query": "q",
            "_context_updates": [{"tc_id": "TC1", "summary": "noise not relevant"}],
        })],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        finish_reason="tool_calls", raw_response={},
    )
    response_t2 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        finish_reason="stop", raw_response={},
    )

    call_count = 0

    async def mock_chat(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return [response_t0, response_t1, response_t2][call_count - 1]

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=mock_chat)):
        await runner.run(user_message="Search q", session_id="rcs-monotonic-sess")

    sess = await manager.load_session("rcs-monotonic-sess")
    # Verify monotonic: each turn's recurring_savings_this_turn >= 0
    running_total = 0
    for turn in sess.turns:
        assert turn.recurring_savings_this_turn >= 0
        running_total += turn.recurring_savings_this_turn
    assert running_total == sess.cumulative_input_tokens_saved_by_rcs
