"""Tests for cross-session memory."""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config import AgentConfig, AgentPersonaConfig, LLMProviderConfig
from nexus.config.memory import MemoryConfig
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
async def test_user_memory_injector_on_plain_system_prompt():
    """Custom system_prompt without Jinja still gets user facts via injector."""
    session = AgentSession(session_id="sess-plain", agent_id="support")
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent = AgentConfig(
        name="support",
        llm=llm,
        memory=MemoryConfig(enabled=True, inject_into_prompt=True),
        persona=AgentPersonaConfig(
            role="Support",
            goal="Help",
            system_prompt="You are support. Be concise.",
        ),
    )
    messages = ContextWindowBuilder().build(
        session,
        agent,
        current_user_message="hi",
        user_memory={"timezone": "PST"},
    )
    assert "About this user" in messages[0]["content"]
    assert "PST" in messages[0]["content"]


@pytest.mark.asyncio
async def test_cross_session_inject_in_system_prompt():
    session = AgentSession(session_id="sess-2", agent_id="support")
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent = AgentConfig(
        name="support",
        llm=llm,
        memory=MemoryConfig(enabled=True),
    )
    messages = ContextWindowBuilder().build(
        session,
        agent,
        current_user_message="hi",
        user_memory={"preference": "dark mode"},
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
        memory=MemoryConfig(enabled=True),
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

    assert runner._user_memory.get("language") == "Spanish"


@pytest.mark.asyncio
async def test_curator_writes_to_cross_session_store():
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
            content=json.dumps({"entities": {"contact": "email"}}),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            raw_response={},
        )
    )
    curator = MemoryCurator(
        MemoryConfig(enabled=True),
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


@pytest.mark.asyncio
async def test_runner_loads_multi_store_always_inject():
    """Named inject=always stores are loaded and key-prefixed when merged."""
    from nexus.config.memory import MemoryStoreConfig

    store = InMemoryCrossSessionMemoryStore()
    await store.merge_entities(
        "t1", "u1", "aitalk:user", {"lang": "en"}, max_entities=50
    )
    await store.merge_entities(
        "t1", "u1", "aitalk:memory", {"note": "prefers GST"}, max_entities=50
    )

    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent = AgentConfig(
        name="aitalk",
        llm=llm,
        memory=MemoryConfig(
            enabled=True,
            expose_tools=False,
            extract_after_each_turn=False,
            stores=[
                MemoryStoreConfig(name="user", inject="always", description="Profile"),
                MemoryStoreConfig(name="memory", inject="always", description="Notes"),
            ],
        ),
    )
    runner = AgentRunner(
        config=agent,
        tool_registry=ToolRegistry(),
        storage_config=SessionManager(),
        cross_session_memory_store=store,
        run_context=RunContext(tenant_id="t1", user_id="u1", company_id="42"),
    )
    facts = await runner._load_user_memory()
    assert facts["user/lang"] == "en"
    assert facts["memory/note"] == "prefers GST"


@pytest.mark.asyncio
async def test_char_budget_trims_inject_only():
    from nexus.config.memory import MemoryStoreConfig

    store = InMemoryCrossSessionMemoryStore()
    await store.merge_entities(
        "t1",
        "u1",
        "aitalk:memory",
        {
            "a": "short",
            "b": "this is a much longer value that should be trimmed",
        },
        max_entities=50,
    )
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    agent = AgentConfig(
        name="aitalk",
        llm=llm,
        memory=MemoryConfig(
            enabled=True,
            stores=[
                MemoryStoreConfig(name="memory", inject="always", char_budget=20),
            ],
        ),
    )
    runner = AgentRunner(
        config=agent,
        tool_registry=ToolRegistry(),
        storage_config=SessionManager(),
        cross_session_memory_store=store,
        run_context=RunContext(tenant_id="t1", user_id="u1"),
    )
    facts = await runner._load_user_memory()
    # Soft trim for inject; store still has both keys.
    record = await store.load("t1", "u1", "aitalk:memory")
    assert len(record.entity_memory) == 2
    assert sum(len(f"{k}: {v}") for k, v in facts.items()) <= 20 + 5  # small slack for single line


def test_memory_injector_multi_store_sections():
    from nexus.config.memory import MemoryStoreConfig
    from nexus.context.memory_injector import MemoryPromptInjector

    cfg = MemoryConfig(
        enabled=True,
        stores=[
            MemoryStoreConfig(name="user", description="USER PROFILE", inject="always"),
            MemoryStoreConfig(name="memory", description="MEMORY", inject="always"),
        ],
    )
    block = MemoryPromptInjector.inject(
        "You are helpful.",
        {"user/lang": "en", "memory/note": "GST"},
        cfg,
    )
    assert "### USER PROFILE" in block
    assert "### MEMORY" in block
    assert "- lang: en" in block
    assert "- note: GST" in block


@pytest.mark.asyncio
async def test_company_id_forwarded_on_load():
    """Custom stores receive company_id from the runner."""
    calls: list[dict] = []

    class TrackingStore(InMemoryCrossSessionMemoryStore):
        async def load(self, tenant_id, user_id, namespace, *, company_id=None):
            calls.append({"company_id": company_id, "namespace": namespace})
            return await super().load(
                tenant_id, user_id, namespace, company_id=company_id
            )

    store = TrackingStore()
    await store.merge_entities(
        "t1", "u1", "bot:user", {"k": "v"}, max_entities=10, company_id="9"
    )
    llm = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    from nexus.config.memory import MemoryStoreConfig

    agent = AgentConfig(
        name="bot",
        llm=llm,
        memory=MemoryConfig(
            enabled=True,
            stores=[MemoryStoreConfig(name="user", inject="always")],
        ),
    )
    runner = AgentRunner(
        config=agent,
        tool_registry=ToolRegistry(),
        storage_config=SessionManager(),
        cross_session_memory_store=store,
        run_context=RunContext(tenant_id="t1", user_id="u1", company_id="9"),
    )
    await runner._load_user_memory()
    assert calls and calls[0]["company_id"] == "9"


def test_persistence_factory_custom_memory_adapter():
    from nexus.config.storage import SessionStorageConfig
    from nexus.persistence.factory import PersistenceFactory

    bundle = PersistenceFactory.from_storage_config(
        SessionStorageConfig(
            adapter="memory",
            custom_memory_adapter_class=(
                "nexus.memory.cross_session_store.InMemoryCrossSessionMemoryStore"
            ),
        )
    )
    assert isinstance(
        bundle.cross_session_memory_store, InMemoryCrossSessionMemoryStore
    )
