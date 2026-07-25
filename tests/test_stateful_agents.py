"""Tests for durable session state, HITL, and turn-end hooks."""

from unittest.mock import AsyncMock, patch

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.storage import SessionStorageConfig
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.hooks import TurnContext, TurnDecision
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


def _agent_config(*, stream_output: bool = False, **turn_kwargs) -> AgentConfig:
    from nexus.config.agent import TurnConfig

    turns = TurnConfig(**turn_kwargs) if turn_kwargs else TurnConfig()
    return AgentConfig(
        name="state-agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key"),
        turns=turns,
        stream_output=stream_output,
    )


def _final_response(content: str = "Done.") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        finish_reason="stop",
        raw_response={},
    )


@tool(name="mark_escalated")
def mark_escalated(ctx: RunContext) -> str:
    ctx.set_state("escalated", True)
    return "marked"


@pytest.mark.asyncio
async def test_state_survives_second_run():
    registry = ToolRegistry()
    registry.register_tool(mark_escalated)
    manager = SessionManager()
    runner = AgentRunner(
        config=_agent_config(),
        tool_registry=registry,
        storage_config=manager,
    )

    turn_tool = LLMResponse(
        content="Checking.",
        tool_calls=[
            ToolCallRequest(
                id="c1",
                tool_name="global.mark_escalated",
                tool_input={},
            )
        ],
        usage=TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6),
        finish_reason="tool_calls",
        raw_response={},
    )
    turn_done = _final_response("All set.")

    mock_chat = AsyncMock(side_effect=[turn_tool, turn_done, _final_response()])
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        r1 = await runner.run("go", session_id="state-s1")
        assert r1.status == "completed"
        assert r1.state.get("escalated") is True

        runner2 = AgentRunner(
            config=_agent_config(),
            tool_registry=registry,
            storage_config=manager,
        )
        with patch.object(runner2.llm_proxy, "chat", AsyncMock(return_value=_final_response("again"))):
            r2 = await runner2.run("follow up", session_id="state-s1")
            assert r2.state.get("escalated") is True


@pytest.mark.asyncio
async def test_initial_context_seeds_state_run_and_stream():
    manager = SessionManager()
    runner = AgentRunner(
        config=_agent_config(),
        tool_registry=ToolRegistry(),
        storage_config=manager,
    )

    mock_chat = AsyncMock(return_value=_final_response())
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        r = await runner.run(
            "hi",
            session_id="seed-1",
            initial_context={"customer_id": "c-9"},
        )
        assert r.state["customer_id"] == "c-9"

    stream_runner = AgentRunner(
        config=_agent_config(stream_output=True),
        tool_registry=ToolRegistry(),
        storage_config=manager,
    )
    with patch.object(stream_runner.llm_proxy, "chat", AsyncMock(return_value=_final_response())):
        async for _ in stream_runner.run_stream(
            "again",
            session_id="seed-2",
            initial_context={"plan_tier": "pro"},
        ):
            pass
    sess = await manager.load_session("seed-2")
    assert sess is not None
    assert sess.state.get("plan_tier") == "pro"


@pytest.mark.asyncio
async def test_state_not_persisted_when_should_persist_false():
    manager = SessionManager()
    registry = ToolRegistry()
    registry.register_tool(mark_escalated)
    ctx = RunContext(is_cron=True, session_id="cron-s1")
    runner = AgentRunner(
        config=_agent_config(),
        tool_registry=registry,
        storage_config=manager,
        run_context=ctx,
    )

    turn_tool = LLMResponse(
        content="x",
        tool_calls=[
            ToolCallRequest(
                id="c1",
                tool_name="global.mark_escalated",
                tool_input={},
            )
        ],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="tool_calls",
        raw_response={},
    )
    mock_chat = AsyncMock(side_effect=[turn_tool, _final_response()])
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run("cron job", session_id="cron-s1")
        assert result.state.get("escalated") is True

    other_manager = SessionManager()
    assert await other_manager.load_session("cron-s1") is None


@pytest.mark.asyncio
async def test_human_in_loop_pauses_and_resume_continues():
    manager = SessionManager()
    runner = AgentRunner(
        config=_agent_config(human_in_loop_after_turns=1),
        tool_registry=ToolRegistry(),
        storage_config=manager,
    )
    mock_chat = AsyncMock(return_value=_final_response("first reply"))
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        paused = await runner.run("hello", session_id="hitl-1")
        assert paused.status == "paused"
        assert any(p.get("tool_name") == "human_in_loop" for p in paused.pending_interactions)

        runner2 = AgentRunner(
            config=_agent_config(human_in_loop_after_turns=None),
            tool_registry=ToolRegistry(),
            storage_config=manager,
        )
        mock_chat2 = AsyncMock(return_value=_final_response("after human"))
        with patch.object(runner2.llm_proxy, "chat", mock_chat2):
            resumed = await runner2.resume(
                "hitl-1",
                results=[{"tc_id": "HITL", "content": "approved"}],
            )
            assert resumed.status == "completed"


@pytest.mark.asyncio
async def test_on_turn_end_stop_and_inject():
    manager = SessionManager()
    decisions = iter([TurnDecision(action="inject", message="injected user line"), None])

    async def hook(_ctx: TurnContext):
        return next(decisions, None)

    runner = AgentRunner(
        config=_agent_config(max_turns=5),
        tool_registry=ToolRegistry(),
        storage_config=manager,
        on_turn_end=hook,
    )
    responses = [_final_response("one"), _final_response("two")]
    mock_chat = AsyncMock(side_effect=responses)
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run("start", session_id="hook-inject")
        assert result.final_response == "two"
        assert mock_chat.call_count == 2

    async def bad_hook(_ctx: TurnContext):
        raise RuntimeError("boom")

    runner_bad = AgentRunner(
        config=_agent_config(),
        tool_registry=ToolRegistry(),
        storage_config=manager,
        on_turn_end=bad_hook,
    )
    with patch.object(runner_bad.llm_proxy, "chat", AsyncMock(return_value=_final_response())):
        ok = await runner_bad.run("x", session_id="hook-err")
        assert ok.status == "completed"

    async def stop_hook(_ctx: TurnContext):
        return TurnDecision(action="stop")

    stop_runner = AgentRunner(
        config=_agent_config(),
        tool_registry=ToolRegistry(),
        storage_config=manager,
        on_turn_end=stop_hook,
    )
    with patch.object(stop_runner.llm_proxy, "chat", AsyncMock(return_value=_final_response())):
        stopped = await stop_runner.run("y", session_id="hook-stop")
        assert stopped.status == "interrupted"


@pytest.mark.asyncio
async def test_session_json_without_state_field_loads():
    from nexus.session.models import AgentSession

    raw = {
        "session_id": "legacy-1",
        "agent_id": "a",
        "turns": [],
    }
    session = AgentSession.model_validate(raw)
    assert session.state == {}


@pytest.mark.asyncio
async def test_state_sqlite_round_trip(tmp_path):
    storage = SessionStorageConfig(adapter="sqlite", adapter_config={"data_root": str(tmp_path)})

    registry = ToolRegistry()
    registry.register_tool(mark_escalated)
    runner = AgentRunner(
        config=_agent_config(),
        tool_registry=registry,
        storage_config=storage,
    )
    turn_tool = LLMResponse(
        content="t",
        tool_calls=[
            ToolCallRequest(
                id="c1",
                tool_name="global.mark_escalated",
                tool_input={},
            )
        ],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="tool_calls",
        raw_response={},
    )
    mock_chat = AsyncMock(side_effect=[turn_tool, _final_response()])
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        await runner.run("persist", session_id="sqlite-state-1")

    manager = runner.session_manager
    loaded = await manager.load_session("sqlite-state-1")
    assert loaded is not None
    assert loaded.state.get("escalated") is True
