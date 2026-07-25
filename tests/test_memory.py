"""Tests for the Nexus memory curator and runner integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.memory import MemoryConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.llm.proxy import LLMProxy
from nexus.llm.response import LLMResponse, TokenUsage
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.memory.curator import MemoryCurator, MemoryUpdate
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


def _session_with_turn(user: str = "Hi", assistant: str = "Hello") -> AgentSession:
    return AgentSession(
        session_id="sess-mem",
        agent_id="agent-1",
        turns=[
            TurnRecord(
                turn_index=0,
                user_message=user,
                llm_messages=[{"role": "assistant", "content": assistant}],
            )
        ],
    )


def test_memory_update_parse_entities():
    update = MemoryUpdate.from_llm_output(
        json.dumps({"entities": {f"k{i}": f"v{i}" for i in range(5)}})
    )
    assert len(update.entities) == 5
    assert update.entities["k0"] == "v0"


def test_memory_update_malformed_json_no_op():
    update = MemoryUpdate.from_llm_output("not json at all")
    assert update.is_empty()


@pytest.mark.parametrize(
    "turn_index,after_each,interval,at_end,extract_at_end,expected",
    [
        (0, True, 0, False, False, True),   # default: after each turn
        (1, True, 0, False, False, True),
        (1, False, 3, False, False, False),  # interval only: turn 1 -> (2)%3!=0
        (2, False, 3, False, False, True),   # interval: turn 2 -> (3)%3==0
        (0, False, 0, False, False, False),  # nothing enabled mid-loop
        (0, True, 0, True, True, False),     # end-of-run skipped if same turn curated
    ],
)
def test_should_trigger_matrix(
    turn_index, after_each, interval, at_end, extract_at_end, expected
):
    cfg = MemoryConfig(
        enabled=True,
        extract_after_each_turn=after_each,
        extraction_interval=interval,
        extract_at_end=extract_at_end,
    )
    curator = MemoryCurator(cfg, MagicMock(spec=LLMProxy), MagicMock())
    if turn_index == 0 and at_end and after_each and not expected:
        curator._last_curated_turn = 0
    assert curator.should_trigger(turn_index, at_end=at_end) is expected


@pytest.mark.asyncio
async def test_curator_disabled_no_llm_call():
    cfg = MemoryConfig(enabled=False)
    curator = MemoryCurator(cfg, MagicMock(spec=LLMProxy), MagicMock())
    session = _session_with_turn()
    mock_chat = AsyncMock()
    curator.llm_proxy = MagicMock()
    curator.llm_proxy.chat = mock_chat

    result = await curator.curate(session, 0)
    assert result.is_empty()
    mock_chat.assert_not_called()


@pytest.mark.asyncio
async def test_curator_llm_writes_to_cross_session_store():
    store = InMemoryCrossSessionMemoryStore()
    manager = SessionManager()
    session = await manager.create_session(
        agent_id="a",
        session_id="cur-sess",
        tenant_id="t",
        user_id="u",
    )
    await manager.append_turn(
        "cur-sess",
        TurnRecord(
            turn_index=0,
            user_message="User likes dark mode",
            llm_messages=[{"role": "assistant", "content": "Noted."}],
        ),
    )
    session = await manager.load_session("cur-sess")

    cfg = MemoryConfig(
        enabled=True,
        max_entities=10,
        extract_after_each_turn=True,
    )
    llm = MagicMock(spec=LLMProxy)
    llm.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps({"entities": {"ui_preference": "dark mode"}}),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            raw_response={},
        )
    )
    curator = MemoryCurator(
        cfg,
        llm,
        manager,
        run_context=RunContext(tenant_id="t", user_id="u"),
        cross_session_memory_store=store,
        agent_name="a",
    )
    await curator.curate(session, 0)

    record = await store.load("t", "u", "a")
    assert record.entity_memory.get("ui_preference") == "dark mode"


@pytest.mark.asyncio
async def test_curator_agent_path_recursion_guard():
    store = InMemoryCrossSessionMemoryStore()
    manager = SessionManager()
    session = await manager.create_session(
        agent_id="main",
        session_id="main-sess",
        tenant_id="t",
        user_id="u",
    )
    await manager.append_turn(
        "main-sess",
        TurnRecord(
            turn_index=0,
            user_message="Remember project Alpha",
            llm_messages=[{"role": "assistant", "content": "OK"}],
        ),
    )
    session = await manager.load_session("main-sess")

    curator_agent_cfg = AgentConfig(
        name="mem-curator",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk"),
        memory=MemoryConfig(enabled=True),  # should be forced off inside curator
    )
    cfg = MemoryConfig(
        enabled=True,
        curator_agent=curator_agent_cfg,
        extract_after_each_turn=True,
    )

    parent_llm = MagicMock(spec=LLMProxy)
    parent_llm.chat = AsyncMock()
    curator = MemoryCurator(
        cfg,
        parent_llm,
        manager,
        tool_registry=ToolRegistry(),
        run_context=RunContext(tenant_id="t", user_id="u"),
        cross_session_memory_store=store,
        agent_name="main",
    )

    json_out = json.dumps({"entities": {"project": "Alpha"}})

    with patch("nexus.runner.agent_runner.AgentRunner") as MockRunner:
        mock_instance = MockRunner.return_value
        mock_instance.run = AsyncMock(
            return_value=MagicMock(final_response=json_out)
        )
        await curator.curate(session, 0)

        call_kwargs = MockRunner.call_args.kwargs
        assert call_kwargs["config"].memory.enabled is False
        parent_llm.chat.assert_not_called()

    record = await store.load("t", "u", "main")
    assert record.entity_memory.get("project") == "Alpha"


@pytest.mark.asyncio
async def test_inject_into_prompt_gate():
    session = AgentSession(session_id="s", agent_id="a")
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_on = AgentConfig(
        name="a",
        llm=llm,
        memory=MemoryConfig(enabled=True, inject_into_prompt=True),
    )
    agent_off = AgentConfig(
        name="a",
        llm=llm,
        memory=MemoryConfig(enabled=True, inject_into_prompt=False),
    )
    builder = ContextWindowBuilder()

    msgs_on = await builder.build(
        session,
        agent_on,
        current_user_message="hi",
        token_budget=10000,
        user_memory={"k": "v"},
    )
    assert "About this user" in msgs_on[0]["content"]

    msgs_off = await builder.build(
        session,
        agent_off,
        current_user_message="hi",
        token_budget=10000,
        user_memory={"k": "v"},
    )
    assert "About this user" not in msgs_off[0]["content"]


@pytest.mark.asyncio
async def test_runner_invokes_curator_at_end():
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="mem-runner",
        llm=llm_config,
        memory=MemoryConfig(
            enabled=True,
            extract_after_each_turn=True,
        ),
    )
    registry = ToolRegistry()
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        finish_reason="stop",
        raw_response={},
    )
    mock_chat = AsyncMock(return_value=response)

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        with patch.object(
            runner.memory_curator, "curate", new_callable=AsyncMock
        ) as mock_curate:
            mock_curate.return_value = MemoryUpdate()
            await runner.run(user_message="Hello", session_id="mem-run-1")
            assert mock_curate.await_count >= 1
