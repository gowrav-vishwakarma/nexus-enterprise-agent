"""Tests for AgentRunner loop execution with mocked LLM."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult
from nexus.tools.registry import ToolRegistry
from nexus.tools.decorators import tool
from nexus.session.manager import SessionManager


@tool(name="web_search")
def web_search(query: str) -> str:
    return f"Search result for {query}"


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
        assert sess.turns[0].tool_calls[0].tool_name == "global.web_search"
        assert sess.turns[0].tool_calls[0].raw_response == "Search result for weather"
        
        # Turn 1 verification
        assert sess.turns[1].user_message is None
        assert len(sess.turns[1].tool_calls) == 0
