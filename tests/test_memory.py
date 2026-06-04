"""Tests for the Nexus memory curator and runner integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.memory import EntityMemoryConfig, SessionMemoryConfig, WorkingMemoryConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.llm.proxy import LLMProxy
from nexus.llm.response import LLMResponse, TokenUsage
from nexus.memory.curator import MemoryCurator, MemoryUpdate
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord
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


def test_memory_update_parse_and_apply_entity_cap():
    update = MemoryUpdate.from_llm_output(
        json.dumps(
            {
                "entities": {f"k{i}": f"v{i}" for i in range(5)},
                "working_memory": "",
            }
        )
    )
    session = AgentSession(session_id="s", agent_id="a", entity_memory={"old": "1"})
    entity_cfg = EntityMemoryConfig(enabled=True, max_entities=3)
    working_cfg = WorkingMemoryConfig(enabled=True, max_length=100)

    changed_e, changed_w = update.apply_to_session(session, entity_cfg, working_cfg)
    assert changed_e
    assert len(session.entity_memory) == 3
    assert "old" not in session.entity_memory  # oldest dropped beyond cap


def test_memory_update_working_truncation():
    update = MemoryUpdate(working_memory="x" * 500)
    session = AgentSession(session_id="s", agent_id="a")
    entity_cfg = EntityMemoryConfig(enabled=False)
    working_cfg = WorkingMemoryConfig(enabled=True, max_length=100)

    _, changed_w = update.apply_to_session(session, entity_cfg, working_cfg)
    assert changed_w
    assert len(session.working_memory) == 100


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
    cfg = SessionMemoryConfig(
        enabled=True,
        entity=EntityMemoryConfig(enabled=True),
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
    cfg = SessionMemoryConfig(enabled=False)
    curator = MemoryCurator(cfg, MagicMock(spec=LLMProxy), MagicMock())
    session = _session_with_turn()
    mock_chat = AsyncMock()
    curator.llm_proxy = MagicMock()
    curator.llm_proxy.chat = mock_chat

    result = await curator.curate(session, 0)
    assert result.is_empty()
    mock_chat.assert_not_called()


@pytest.mark.asyncio
async def test_curator_llm_updates_session():
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="cur-sess")
    await manager.append_turn(
        "cur-sess",
        TurnRecord(
            turn_index=0,
            user_message="User likes dark mode",
            llm_messages=[{"role": "assistant", "content": "Noted."}],
        ),
    )
    session = await manager.load_session("cur-sess")

    cfg = SessionMemoryConfig(
        enabled=True,
        entity=EntityMemoryConfig(enabled=True, max_entities=10),
        working=WorkingMemoryConfig(enabled=True, max_length=200),
        extract_after_each_turn=True,
    )
    llm = MagicMock(spec=LLMProxy)
    llm.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {
                    "entities": {"ui_preference": "dark mode"},
                    "working_memory": "track UI prefs",
                }
            ),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            raw_response={},
        )
    )
    curator = MemoryCurator(cfg, llm, manager)
    await curator.curate(session, 0)

    reloaded = await manager.load_session("cur-sess")
    assert reloaded.entity_memory.get("ui_preference") == "dark mode"
    assert "UI prefs" in reloaded.working_memory


@pytest.mark.asyncio
async def test_curator_agent_path_recursion_guard():
    manager = SessionManager()
    session = await manager.create_session(agent_id="main", session_id="main-sess")
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
        session_memory=SessionMemoryConfig(enabled=True),  # should be forced off inside curator
    )
    cfg = SessionMemoryConfig(
        enabled=True,
        entity=EntityMemoryConfig(enabled=True),
        curator_agent=curator_agent_cfg,
        extract_after_each_turn=True,
    )

    parent_llm = MagicMock(spec=LLMProxy)
    parent_llm.chat = AsyncMock()
    curator = MemoryCurator(cfg, parent_llm, manager, tool_registry=ToolRegistry())

    json_out = json.dumps({"entities": {"project": "Alpha"}, "working_memory": ""})

    with patch("nexus.runner.agent_runner.AgentRunner") as MockRunner:
        mock_instance = MockRunner.return_value
        mock_instance.run = AsyncMock(
            return_value=MagicMock(final_response=json_out)
        )
        await curator.curate(session, 0)

        call_kwargs = MockRunner.call_args.kwargs
        assert call_kwargs["config"].session_memory.enabled is False
        parent_llm.chat.assert_not_called()

    reloaded = await manager.load_session("main-sess")
    assert reloaded.entity_memory.get("project") == "Alpha"


@pytest.mark.asyncio
async def test_inject_into_prompt_gate():
    session = AgentSession(
        session_id="s",
        agent_id="a",
        entity_memory={"k": "v"},
        working_memory="notes",
    )
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_on = AgentConfig(
        name="a",
        llm=llm,
        session_memory=SessionMemoryConfig(enabled=True, inject_into_prompt=True),
    )
    agent_off = AgentConfig(
        name="a",
        llm=llm,
        session_memory=SessionMemoryConfig(enabled=True, inject_into_prompt=False),
    )
    builder = ContextWindowBuilder()

    msgs_on = builder.build(session, agent_on, current_user_message="hi", token_budget=10000)
    assert "Known Facts" in msgs_on[0]["content"]
    assert "Working Notes" in msgs_on[0]["content"]

    msgs_off = builder.build(session, agent_off, current_user_message="hi", token_budget=10000)
    assert "Known Facts" not in msgs_off[0]["content"]
    assert "Working Notes" not in msgs_off[0]["content"]


@pytest.mark.asyncio
async def test_runner_invokes_curator_at_end():
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="mem-runner",
        llm=llm_config,
        session_memory=SessionMemoryConfig(
            enabled=True,
            entity=EntityMemoryConfig(enabled=True),
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
