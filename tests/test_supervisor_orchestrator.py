"""Unit tests for supervisor orchestrator behavior and group fixes."""

from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.runner.result import AgentRunResult
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


def _llm_agent(name: str, *, toolset: str | None = None) -> AgentConfig:
    return AgentConfig(
        name=name,
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role=name, goal="work"),
        toolset=toolset,
    )


@tool(name="support_lookup", description="Look up support info.")
def support_lookup(query: str) -> str:
    return f"Support: {query}"


def test_members_default_to_subagent_run_context():
    group = AgentGroupConfig(
        name="team",
        pattern="pipeline",
        members=[_llm_agent("a"), _llm_agent("b")],
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="g1"),
    )
    assert orch._members["a"].run_context.is_subagent is True
    assert orch._members["b"].run_context.is_subagent is True


def test_persist_members_opt_in():
    group = AgentGroupConfig(
        name="team",
        pattern="pipeline",
        persist_members=True,
        members=[_llm_agent("a")],
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="g1"),
    )
    assert orch._members["a"].run_context.is_subagent is False


def test_select_supervisor_explicit():
    group = AgentGroupConfig(
        name="team",
        pattern="supervisor",
        supervisor="lead",
        members=[_llm_agent("lead"), _llm_agent("worker")],
    )
    orch = AgentOrchestrator(config=group, run_context=RunContext(session_id="g1"))
    name, err = orch._select_supervisor()
    assert err is None
    assert name == "lead"


def test_select_supervisor_invalid_explicit():
    group = AgentGroupConfig(
        name="team",
        pattern="supervisor",
        supervisor="missing",
        members=[_llm_agent("lead")],
    )
    orch = AgentOrchestrator(config=group, run_context=RunContext(session_id="g1"))
    name, err = orch._select_supervisor()
    assert name is None
    assert "not a group member" in (err or "")


def test_select_supervisor_heuristic():
    group = AgentGroupConfig(
        name="team",
        pattern="supervisor",
        members=[_llm_agent("worker"), _llm_agent("team_supervisor")],
    )
    orch = AgentOrchestrator(config=group, run_context=RunContext(session_id="g1"))
    name, err = orch._select_supervisor()
    assert err is None
    assert name == "team_supervisor"


@pytest.mark.asyncio
async def test_pipeline_respects_group_max_turns():
    group = AgentGroupConfig(
        name="pipe",
        pattern="pipeline",
        max_turns=1,
        members=[_llm_agent("first"), _llm_agent("second")],
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="pipe-1"),
    )

    one_turn = AgentRunResult(
        session_id="s",
        final_response="step done",
        turns_used=1,
        status="completed",
        duration_ms=1,
    )

    first_run = AsyncMock(return_value=one_turn)
    second_run = AsyncMock(return_value=one_turn)

    with patch.object(orch._members["first"], "run", first_run), patch.object(
        orch._members["second"], "run", second_run
    ):
        result = await orch.run("go")

    assert result.status == "completed"
    first_run.assert_awaited_once()
    second_run.assert_not_awaited()
    assert "first" in result.member_results
    assert "second" not in result.member_results


@pytest.mark.asyncio
async def test_supervisor_auto_grants_delegate_tools_with_toolset():
    registry = ToolRegistry()
    registry.add_toolset("support", [support_lookup])

    group = AgentGroupConfig(
        name="team",
        pattern="supervisor",
        supervisor="lead",
        members=[
            _llm_agent("lead", toolset="support"),
            _llm_agent("worker"),
        ],
    )
    orch = AgentOrchestrator(
        config=group,
        tool_registry=registry,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="sup-1"),
    )
    lead = orch._members["lead"]

    done = AgentRunResult(
        session_id="lead-s",
        final_response="all set",
        turns_used=1,
        status="completed",
        duration_ms=1,
    )

    async def capture_run(*_args, **_kwargs):
        lead._resolve_toolsets()
        assert "supervisor.delegate_to_worker" in (lead._allowed_tools or set())
        return done

    with patch.object(lead, "run", side_effect=capture_run):
        result = await orch.run("delegate please")

    assert result.status == "completed"
    assert "lead" in result.member_results


@pytest.mark.asyncio
async def test_orchestrator_fans_out_event_emitter():
    from nexus.events.emitter import CustomCallbackSink, NexusEventEmitter
    from nexus.events.models import NexusEventType
    from nexus.llm.response import LLMResponse, TokenUsage

    seen = []

    async def on_event(event):
        seen.append(event)

    emitter = NexusEventEmitter()
    emitter.register_sink(CustomCallbackSink(on_event))

    group = AgentGroupConfig(
        name="team",
        pattern="pipeline",
        members=[_llm_agent("a")],
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="emit-1"),
        event_emitter=emitter,
    )
    assert orch._members["a"].event_emitter is emitter

    reply = LLMResponse(
        content="ok",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        raw_response={},
    )
    with patch.object(orch._members["a"].llm_proxy, "chat", AsyncMock(return_value=reply)):
        await orch.run("hello")

    assert any(e.event_type == NexusEventType.AGENT_STARTED for e in seen)
