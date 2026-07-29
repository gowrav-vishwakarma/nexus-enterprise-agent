"""Tests for AgentRunner loop execution with mocked LLM."""

from unittest.mock import AsyncMock, patch
import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.tools.registry import ToolRegistry
from nexus.tools.decorators import tool
from nexus.session.manager import SessionManager


@tool(name="web_search")
def web_search(query: str) -> str:
    return f"Search result for {query}"


@tool(name="lookup_db")
def lookup_db(table: str) -> str:
    return f"DB row from {table}"


@pytest.mark.asyncio
async def test_agent_runner_loop():
    """Test AgentRunner executing turns, calling tools, and returning results."""
    # Initialize config
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="test-agent",
        llm=llm_config,
    )
    
    # Register tool
    registry = ToolRegistry()
    registry.register_tool(web_search)

    # Initialize runner
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    # Mock the LLMProxy chat call to simulate 2 turns:
    # Turn 0: LLM requests tool call (web_search)
    # Turn 1: LLM outputs final answer (no tool calls)
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage
    
    response_turn_0 = LLMResponse(
        content="Let me look that up.",
        tool_calls=[
            ToolCallRequest(id="call-1", tool_name="global.web_search", tool_input={"query": "weather"})
        ],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=15, total_tokens=25),
        finish_reason="tool_calls",
        raw_response={},
    )
    
    response_turn_1 = LLMResponse(
        content="It is sunny.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        finish_reason="stop",
        raw_response={},
    )

    mock_chat = AsyncMock()
    mock_chat.side_effect = [response_turn_0, response_turn_1]

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(user_message="What is the weather?", session_id="runner-sess-1")

        # Verify results
        assert isinstance(result, AgentRunResult)
        assert result.session_id == "runner-sess-1"
        assert result.final_response == "It is sunny."
        assert result.turns_used == 2
        assert result.status == "completed"
        assert result.total_tokens_in == 30
        assert result.total_tokens_out == 20

        # Verify session turns and tool calls were saved in persistence
        sess = await manager.load_session("runner-sess-1")
        assert sess is not None
        assert len(sess.turns) == 2
        
        # Turn 0 verification
        assert sess.turns[0].user_message == "What is the weather?"
        assert len(sess.turns[0].tool_calls) == 1
        assert sess.turns[0].tool_calls[0].tc_id == "TC1"
        assert sess.turns[0].tool_calls[0].tc_index == 1
        assert sess.turns[0].tool_calls[0].tool_name == "global.web_search"
        assert sess.turns[0].tool_calls[0].raw_response == "Search result for weather"
        
        # Turn 1 verification
        assert sess.turns[1].user_message is None
        assert len(sess.turns[1].tool_calls) == 0


@pytest.mark.asyncio
async def test_agent_runner_streaming_parity():
    """Streaming and blocking modes produce the same final result and session state."""
    from nexus.llm.response import LLMResponse, LLMStreamChunk, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(name="test-agent", llm=llm_config)

    registry = ToolRegistry()
    registry.register_tool(web_search)

    manager_blocking = SessionManager()
    manager_streaming = SessionManager()

    runner_blocking = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager_blocking,
    )
    runner_streaming = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager_streaming,
    )

    response_turn_0 = LLMResponse(
        content="Let me look that up.",
        tool_calls=[
            ToolCallRequest(id="call-1", tool_name="global.web_search", tool_input={"query": "weather"})
        ],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=15, total_tokens=25),
        finish_reason="tool_calls",
        raw_response={},
    )
    response_turn_1 = LLMResponse(
        content="It is sunny.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        finish_reason="stop",
        raw_response={},
    )

    stream_turn_chunks = [
        [
            LLMStreamChunk(content="Let me look that up."),
            LLMStreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-1",
                        "name": "global.web_search",
                        "arguments": '{"query": "weather"}',
                    }
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=15, total_tokens=25),
            ),
        ],
        [
            LLMStreamChunk(content="It is "),
            LLMStreamChunk(
                content="sunny.",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
            ),
        ],
    ]
    stream_call_idx = 0

    async def mock_chat_stream(*_args, **_kwargs):
        nonlocal stream_call_idx
        chunks = stream_turn_chunks[stream_call_idx]
        stream_call_idx += 1

        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()

    mock_chat = AsyncMock(side_effect=[response_turn_0, response_turn_1])

    with patch.object(runner_blocking.llm_proxy, "chat", mock_chat):
        blocking_result = await runner_blocking.run(
            user_message="What is the weather?",
            session_id="blocking-sess",
            stream=False,
        )

    with patch.object(runner_streaming.llm_proxy, "chat_stream", mock_chat_stream):
        events: list[AgentStreamEvent] = []
        async for event in runner_streaming.run_stream(
            user_message="What is the weather?",
            session_id="streaming-sess",
            stream=True,
        ):
            events.append(event)

    stream_final = next(e for e in events if e.event_type == "final_response")
    streaming_result = AgentRunResult(**stream_final.data)

    assert blocking_result.final_response == streaming_result.final_response == "It is sunny."
    assert blocking_result.turns_used == streaming_result.turns_used == 2
    assert blocking_result.total_tokens_in == streaming_result.total_tokens_in == 30
    assert blocking_result.total_tokens_out == streaming_result.total_tokens_out == 20

    content_events = [e for e in events if e.event_type == "content"]
    assert any(e.content == "It is " for e in content_events)
    assert any(e.content == "sunny." for e in content_events)
    # Narration on a tool turn is real assistant output and is streamed live too.
    assert any(e.content == "Let me look that up." for e in content_events)

    tool_call_events = [e for e in events if e.event_type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].data["tool_name"] == "global.web_search"

    blocking_sess = await manager_blocking.load_session("blocking-sess")
    streaming_sess = await manager_streaming.load_session("streaming-sess")
    assert blocking_sess is not None and streaming_sess is not None
    assert len(blocking_sess.turns) == len(streaming_sess.turns) == 2


@pytest.mark.asyncio
async def test_agent_runner_stream_multi_turn_deltas_are_live():
    """Every delta reaches the client as it arrives, in occurrence order.

    Three turns: web_search → lookup_db → final answer. Each turn's narration is
    streamed before that turn's tool_call, so a UI can render text, tool chips and
    the final answer as one ordered timeline.
    """
    from nexus.llm.response import LLMStreamChunk, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="test-agent",
        llm=llm_config,
        tool_plugins=["global"],
    )

    registry = ToolRegistry()
    registry.register_tool(web_search)
    registry.register_tool(lookup_db)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    stream_turn_chunks = [
        # Turn 0: narration then a tool call — both reach the client
        [
            LLMStreamChunk(content="Searching weather..."),
            LLMStreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-1",
                        "name": "global.web_search",
                        "arguments": '{"query": "weather"}',
                    }
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            ),
        ],
        # Turn 1: second narration + tool call — same rule
        [
            LLMStreamChunk(content="Now checking database..."),
            LLMStreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-2",
                        "name": "global.lookup_db",
                        "arguments": '{"table": "forecasts"}',
                    }
                ],
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=15, completion_tokens=9, total_tokens=24),
            ),
        ],
        # Turn 2: final answer — content IS streamed
        [
            LLMStreamChunk(content="Weather is "),
            LLMStreamChunk(
                content="sunny and DB says clear.",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            ),
        ],
    ]
    stream_call_idx = 0

    async def mock_chat_stream(*_args, **_kwargs):
        nonlocal stream_call_idx
        chunks = stream_turn_chunks[stream_call_idx]
        stream_call_idx += 1

        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()

    events: list[AgentStreamEvent] = []
    with patch.object(runner.llm_proxy, "chat_stream", mock_chat_stream):
        async for event in runner.run_stream(
            user_message="Full weather report?",
            session_id="multi-tool-stream",
            stream=True,
        ):
            events.append(event)

    final = next(e for e in events if e.event_type == "final_response")
    result = AgentRunResult(**final.data)

    assert result.turns_used == 3
    assert result.final_response == "Weather is sunny and DB says clear."
    assert result.status == "completed"

    content_events = [e for e in events if e.event_type == "content"]
    tool_call_events = [e for e in events if e.event_type == "tool_call"]
    tool_result_events = [e for e in events if e.event_type == "tool_result"]

    assert len(tool_call_events) == 2
    assert len(tool_result_events) == 2
    assert tool_call_events[0].data["turn_index"] == 0
    assert tool_call_events[0].data["tool_name"] == "global.web_search"
    assert tool_call_events[1].data["turn_index"] == 1
    assert tool_call_events[1].data["tool_name"] == "global.lookup_db"
    assert tool_result_events[0].data["turn_index"] == 0
    assert "Search result for weather" in tool_result_events[0].content
    assert tool_result_events[1].data["turn_index"] == 1
    assert "DB row from forecasts" in tool_result_events[1].content

    # Every delta is streamed, each tagged with the turn it came from
    assert [(e.data.get("turn_index"), e.content) for e in content_events] == [
        (0, "Searching weather..."),
        (1, "Now checking database..."),
        (2, "Weather is "),
        (2, "sunny and DB says clear."),
    ]

    # Nothing is held back: each turn's narration arrives before that turn's tool_call
    timeline = [
        (e.event_type, e.data.get("turn_index") if e.data else None, e.content)
        for e in events
        if e.event_type in ("tool_call", "tool_result", "content")
    ]
    order = [
        ("content", 0, "Searching weather..."),
        ("tool_call", 0, None),
        ("tool_result", 0, "Search result for weather"),
        ("content", 1, "Now checking database..."),
        ("tool_call", 1, None),
        ("tool_result", 1, "DB row from forecasts"),
        ("content", 2, "Weather is "),
        ("content", 2, "sunny and DB says clear."),
    ]
    assert [timeline.index(step) for step in order] == sorted(
        timeline.index(step) for step in order
    )

    sess = await manager.load_session("multi-tool-stream")
    assert sess is not None
    assert len(sess.turns) == 3
    assert len(sess.turns[0].tool_calls) == 1
    assert len(sess.turns[1].tool_calls) == 1
    assert len(sess.turns[2].tool_calls) == 0


@pytest.mark.asyncio
async def test_agent_runner_stream_reasoning_events_and_persistence():
    """Reasoning deltas stream as their own event type and persist on the turn."""
    from nexus.llm.response import LLMStreamChunk, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(name="test-agent", llm=llm_config)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=ToolRegistry(),
        storage_config=manager,
    )

    chunks = [
        LLMStreamChunk(reasoning="The user wants "),
        LLMStreamChunk(reasoning="the weather."),
        LLMStreamChunk(content="It is "),
        LLMStreamChunk(
            content="sunny.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ),
    ]

    async def mock_chat_stream(*_args, **_kwargs):
        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()

    events: list[AgentStreamEvent] = []
    with patch.object(runner.llm_proxy, "chat_stream", mock_chat_stream):
        async for event in runner.run_stream(
            user_message="What is the weather?",
            session_id="reasoning-sess",
            stream=True,
        ):
            events.append(event)

    # Reasoning is a separate channel — it never leaks into content
    reasoning_events = [e for e in events if e.event_type == "reasoning"]
    content_events = [e for e in events if e.event_type == "content"]
    assert [e.content for e in reasoning_events] == ["The user wants ", "the weather."]
    assert [e.content for e in content_events] == ["It is ", "sunny."]

    # Reasoning arrives before the answer it explains
    assert events.index(reasoning_events[-1]) < events.index(content_events[0])

    final = next(e for e in events if e.event_type == "final_response")
    assert AgentRunResult(**final.data).final_response == "It is sunny."

    sess = await manager.load_session("reasoning-sess")
    assert sess is not None
    assert sess.turns[0].reasoning == "The user wants the weather."
    # Stored outside llm_messages, which are replayed verbatim into the provider
    assert all("reasoning" not in m for m in sess.turns[0].llm_messages)


@pytest.mark.asyncio
async def test_agent_runner_xml_tool_call_in_content_promotes_and_executes():
    """XML tool calls in assistant content are promoted and executed like native tool_calls."""
    from nexus.llm.response import LLMResponse, TokenUsage

    @tool(name="execute_sql")
    def execute_sql(sql: str) -> str:
        return f"rows:1 sql_len={len(sql)}"

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(name="test-agent", llm=llm_config)

    registry = ToolRegistry()
    registry.register_tool(execute_sql)
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    xml_content = (
        "Checking balances:\n"
        "<tool_call><function=execute_sql>"
        "<parameter=sql>SELECT 1</parameter></function></tool_call>"
    )
    response_turn_0 = LLMResponse(
        content=xml_content,
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
        raw_response={},
    )
    response_turn_1 = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=30, completion_tokens=5, total_tokens=35),
        finish_reason="stop",
        raw_response={},
    )

    mock_chat = AsyncMock()
    mock_chat.side_effect = [response_turn_0, response_turn_1]

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(user_message="Show balances", session_id="xml-sess")

    assert result.turns_used == 2
    sess = await manager.load_session("xml-sess")
    assert sess is not None
    assert len(sess.turns[0].tool_calls) == 1
    assert sess.turns[0].tool_calls[0].tool_name == "execute_sql"
    assistant_msg = sess.turns[0].llm_messages[0]
    assert "<tool_call>" not in str(assistant_msg.get("content") or "")
    assert assistant_msg.get("tool_calls")


@pytest.mark.asyncio
async def test_agent_runner_stream_mode_guard():
    """run() rejects streaming mode; run_stream() rejects non-streaming mode."""
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(name="test-agent", llm=llm_config, stream_output=True)
    runner = AgentRunner(config=agent_config, tool_registry=ToolRegistry())

    with pytest.raises(ValueError, match="run_stream"):
        await runner.run("hello")

    agent_config_blocking = AgentConfig(name="test-agent", llm=llm_config, stream_output=False)
    runner_blocking = AgentRunner(config=agent_config_blocking, tool_registry=ToolRegistry())

    with pytest.raises(ValueError, match="run\\(\\)"):
        async for _ in runner_blocking.run_stream("hello"):
            pass
