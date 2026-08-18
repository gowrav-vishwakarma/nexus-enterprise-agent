"""Tests for BuiltInSemanticMemoryProvider."""

import pytest

from nexus.config.memory import MemoryConfig, MemoryStoreConfig
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.memory.providers.builtin_semantic import BuiltInSemanticMemoryProvider
from nexus.tools.context import RunContext


@pytest.mark.asyncio
async def test_write_prefetch_search_remove():
    store = InMemoryCrossSessionMemoryStore()
    provider = BuiltInSemanticMemoryProvider(
        store, MemoryConfig(enabled=True, namespace="agent"), agent_name="agent"
    )
    ctx = RunContext(tenant_id="acme", user_id="u1", company_id="co1")
    await provider.write(ctx, "name", "Ada Lovelace")
    await provider.write(ctx, "city", "London")
    facts = await provider.prefetch(ctx)
    assert facts["name"] == "Ada Lovelace"
    hits = await provider.search(ctx, "Ada", k=5)
    assert any(h["key"] == "name" for h in hits)
    await provider.remove(ctx, "city")
    facts = await provider.prefetch(ctx)
    assert "city" not in facts


@pytest.mark.asyncio
async def test_tenant_isolation():
    store = InMemoryCrossSessionMemoryStore()
    provider = BuiltInSemanticMemoryProvider(store, MemoryConfig(namespace="n"), agent_name="n")
    a = RunContext(tenant_id="a", user_id="u1")
    b = RunContext(tenant_id="b", user_id="u1")
    await provider.write(a, "secret", "alpha-only")
    await provider.write(b, "secret", "beta-only")
    assert (await provider.prefetch(a))["secret"] == "alpha-only"
    assert (await provider.prefetch(b))["secret"] == "beta-only"
    assert all("beta" not in h["value"] for h in await provider.search(a, "secret"))


@pytest.mark.asyncio
async def test_named_stores_prefetch_always_only():
    store = InMemoryCrossSessionMemoryStore()
    config = MemoryConfig(
        enabled=True,
        namespace="bot",
        stores=[
            MemoryStoreConfig(name="user", inject="always"),
            MemoryStoreConfig(name="notes", inject="on_recall"),
        ],
    )
    provider = BuiltInSemanticMemoryProvider(store, config, agent_name="bot")
    ctx = RunContext(tenant_id="t", user_id="u")
    await provider.write(ctx, "role", "cfo", store="user")
    await provider.write(ctx, "draft", "hidden note", store="notes")
    facts = await provider.prefetch(ctx)
    assert "role" in facts or "user/role" in facts
    assert "draft" not in facts and "notes/draft" not in facts
    hits = await provider.search(ctx, "hidden", k=5)
    assert any(h["key"] == "draft" for h in hits)
