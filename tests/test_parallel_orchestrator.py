"""Tests for the parallel multi-agent orchestrator pattern."""

from unittest.mock import patch

import pytest

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext


def _agent(name: str) -> AgentConfig:
    return AgentConfig(
        name=name,
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role=name, goal="answer"),
    )


def _group(strategy="concat") -> AgentGroupConfig:
    return AgentGroupConfig(
        name="panel",
        pattern="parallel",
        members=[_agent("alpha"), _agent("beta")],
        aggregation_strategy=strategy,
    )


def _chat_stream_for(reply: str):
    async def chat_stream(*a, **k):
        async def gen():
            yield LLMStreamChunk(content=reply)
            yield LLMStreamChunk(content=None, finish_reason="stop", usage=TokenUsage())
        return gen()

    return chat_stream


def _chat_for(reply: str):
    async def chat(*a, **k):
        return LLMResponse(content=reply, tool_calls=[], finish_reason="stop", usage=TokenUsage())

    return chat


def _build(group):
    return AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="panel-1"),
    )


@pytest.mark.asyncio
async def test_parallel_concat_aggregation():
    orch = _build(_group("concat"))
    with patch.object(
        orch._members["alpha"].llm_proxy, "chat", _chat_for("A says hi")
    ), patch.object(
        orch._members["beta"].llm_proxy, "chat", _chat_for("B says hi")
    ):
        result = await orch.run("question")

    assert result.status == "completed"
    assert "[alpha]" in result.final_response
    assert "[beta]" in result.final_response
    assert "A says hi" in result.final_response and "B says hi" in result.final_response
    assert set(result.member_results.keys()) == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_parallel_first_complete():
    orch = _build(_group("first_complete"))
    with patch.object(
        orch._members["alpha"].llm_proxy, "chat", _chat_for("only A")
    ), patch.object(
        orch._members["beta"].llm_proxy, "chat", _chat_for("only B")
    ):
        result = await orch.run("question")
    assert result.final_response in ("only A", "only B")


@pytest.mark.asyncio
async def test_parallel_stream_multiplexes_members():
    orch = _build(_group("concat"))
    with patch.object(
        orch._members["alpha"].llm_proxy, "chat_stream", _chat_stream_for("A1")
    ), patch.object(
        orch._members["beta"].llm_proxy, "chat_stream", _chat_stream_for("B1")
    ):
        events = [ev async for ev in orch.run_stream("question", stream=True)]

    final = [e for e in events if e.event_type == "final_response"][-1]
    assert "[alpha]" in final.content and "[beta]" in final.content


# =============================================================================
# RCS token-savings aggregation across group members
# =============================================================================

@pytest.mark.asyncio
async def test_parallel_rcs_token_savings_aggregate():
    """Group result sums RCS savings from each member."""
    from nexus.config.rcs import RuntimeContextSummarizerConfig
    from nexus.runner.result import AgentRunResult

    agent_alpha = AgentConfig(
        name="alpha",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role="alpha", goal="answer"),
        rcs=RuntimeContextSummarizerConfig(enabled=True),
    )
    agent_beta = AgentConfig(
        name="beta",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role="beta", goal="answer"),
        rcs=RuntimeContextSummarizerConfig(enabled=True),
    )
    group = AgentGroupConfig(
        name="rcs-panel",
        pattern="parallel",
        members=[agent_alpha, agent_beta],
        aggregation_strategy="concat",
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="rcs-panel-1"),
    )

    # Mock each member runner's run() to return a result with RCS savings
    alpha_result = AgentRunResult(
        session_id="alpha-sess", final_response="A done", turns_used=1,
        total_tokens_in=100, total_tokens_out=20, total_tokens_saved_by_rcs=150,
        cumulative_input_tokens_saved_by_rcs=450,
        duration_ms=10, status="completed",
    )
    beta_result = AgentRunResult(
        session_id="beta-sess", final_response="B done", turns_used=1,
        total_tokens_in=200, total_tokens_out=30, total_tokens_saved_by_rcs=250,
        cumulative_input_tokens_saved_by_rcs=750,
        duration_ms=10, status="completed",
    )

    async def alpha_run(*_a, **_kw):
        return alpha_result

    async def beta_run(*_a, **_kw):
        return beta_result

    with patch.object(orch._members["alpha"], "run", alpha_run), \
         patch.object(orch._members["beta"], "run", beta_run):
        result = await orch.run("question")

    assert result.status == "completed"
    assert result.total_tokens_saved_by_rcs == 150 + 250
    assert result.total_tokens_saved_by_rcs == alpha_result.total_tokens_saved_by_rcs + beta_result.total_tokens_saved_by_rcs
    assert result.cumulative_tokens_saved_by_rcs == 450 + 750
    assert result.cumulative_tokens_saved_by_rcs == alpha_result.cumulative_input_tokens_saved_by_rcs + beta_result.cumulative_input_tokens_saved_by_rcs
