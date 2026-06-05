"""Tests for cross-session memory."""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.memory import (
    CrossSessionMemoryConfig,
    EntityMemoryConfig,
    SessionMemoryConfig,
)
from nexus.context.builder import ContextWindowBuilder
from nexus.llm.response import LLMResponse, TokenUsage
from nexus.memory.cross_session_store import (
    InMemoryCrossSessionMemoryStore,
    SQLiteCrossSessionMemoryStore,
)
from nexus.storage.paths import memory_db_path
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_cross_session_store_merge_and_cap():
    store = InMemoryCrossSessionMemoryStore()
    for i in range(5):
        await store.merge_entities(
            "tenant-a",
            "user-1",
            "agent",
            {f"k{i}": f"v{i}"},
            max_entities=3,
        )
    record = await store.load("tenant-a", "user-1", "agent")
    assert len(record.entity_memory) == 3
    assert "k0" not in record.entity_memory
    assert "k4" in record.entity_memory


@pytest.mark.asyncio
async def test_cross_session_inject_in_system_prompt():
    store = InMemoryCrossSessionMemoryStore()
    await store.merge_entities(
        "t1",
        "alice",
        "support",
        {"preference": "dark mode"},
        max_entities=50,
    )

    session = AgentSession(session_id="sess-2", agent_id="support")
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent = AgentConfig(
        name="support",
        llm=llm,
        session_memory=SessionMemoryConfig(
            enabled=True,
            entity=EntityMemoryConfig(enabled=True),
            cross_session=CrossSessionMemoryConfig(enabled=True),
        ),
    )
    messages = ContextWindowBuilder().build(
        session,
        agent,
        current_user_message="hi",
        cross_session_entity_memory={"preference": "dark mode"},
    )
    assert "About this user" in messages[0]["content"]
    assert "dark mode" in messages[0]["content"]


@pytest.mark.asyncio
async def test_cross_session_isolation_between_users():
    store = InMemoryCrossSessionMemoryStore()
    await store.merge_entities("t", "user-a", "a", {"x": "1"}, max_entities=10)
    await store.merge_entities("t", "user-b", "a", {"y": "2"}, max_entities=10)

    rec_a = await store.load("t", "user-a", "a")
    rec_b = await store.load("t", "user-b", "a")
    assert rec_a.entity_memory == {"x": "1"}
    assert rec_b.entity_memory == {"y": "2"}


@pytest.mark.asyncio
async def test_runner_loads_cross_session_memory_on_new_session():
    store = InMemoryCrossSessionMemoryStore()
    await store.merge_entities(
        "tenant",
        "u1",
        "bot",
        {"language": "Spanish"},
        max_entities=50,
    )

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent_config = AgentConfig(
        name="bot",
        llm=llm_config,
        session_memory=SessionMemoryConfig(
            enabled=True,
            entity=EntityMemoryConfig(enabled=True),
            cross_session=CrossSessionMemoryConfig(enabled=True),
        ),
    )
    registry = ToolRegistry()
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
        run_context=RunContext(tenant_id="tenant", user_id="u1"),
        cross_session_memory_store=store,
    )

    response = LLMResponse(
        content="Hola.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        finish_reason="stop",
        raw_response={},
    )

    mock_curate = AsyncMock(return_value=MagicMock(is_empty=lambda: True))
    with patch.object(runner.llm_proxy, "chat", AsyncMock(return_value=response)):
        with patch.object(runner.memory_curator, "curate", mock_curate):
            await runner.run(user_message="Hello", session_id="brand-new-session")

    assert runner._cross_session_entity_memory.get("language") == "Spanish"


@pytest.mark.asyncio
async def test_curator_promotes_to_cross_session_store():
    store = InMemoryCrossSessionMemoryStore()
    manager = SessionManager()
    session = await manager.create_session(
        agent_id="bot",
        session_id="s1",
        tenant_id="t",
        user_id="u1",
    )
    await manager.append_turn(
        "s1",
        TurnRecord(
            turn_index=0,
            user_message="I prefer email contact",
            llm_messages=[{"role": "assistant", "content": "Noted."}],
        ),
    )
    session = await manager.load_session("s1")

    from nexus.memory.curator import MemoryCurator

    llm = MagicMock()
    llm.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {"entities": {"contact": "email"}, "working_memory": ""}
            ),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            raw_response={},
        )
    )
    curator = MemoryCurator(
        SessionMemoryConfig(
            enabled=True,
            entity=EntityMemoryConfig(enabled=True),
            cross_session=CrossSessionMemoryConfig(enabled=True),
        ),
        llm,
        manager,
        run_context=RunContext(tenant_id="t", user_id="u1"),
        cross_session_memory_store=store,
        agent_name="bot",
    )
    await curator.curate(session, 0)

    record = await store.load("t", "u1", "bot")
    assert record.entity_memory.get("contact") == "email"


@pytest.mark.asyncio
async def test_sqlite_cross_session_memory_tenant_scoped():
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SQLiteCrossSessionMemoryStore(data_root=tmpdir, tenant_scoped=True)
        await store.merge_entities(
            "tenant-a",
            "user-1",
            "agent",
            {"preference": "email"},
            max_entities=50,
        )

        db_path = memory_db_path("tenant-a", "user-1", data_root=tmpdir)
        assert db_path.exists()

        record = await store.load("tenant-a", "user-1", "agent")
        assert record.entity_memory["preference"] == "email"

        await store.merge_entities(
            "tenant-a",
            "user-2",
            "agent",
            {"preference": "sms"},
            max_entities=50,
        )
        other_db = memory_db_path("tenant-a", "user-2", data_root=tmpdir)
        assert other_db.exists()
        assert other_db != db_path

        user2 = await store.load("tenant-a", "user-2", "agent")
        assert user2.entity_memory["preference"] == "sms"


