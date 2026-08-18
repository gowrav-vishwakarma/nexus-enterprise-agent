"""HITL memory approval: pending writes are not injected until approved."""

import json

import pytest

from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.memory.plugin import HITLMemoryPlugin, create_memory_plugin
from nexus.memory.providers.builtin_semantic import BuiltInSemanticMemoryProvider
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_require_approval_hides_pending_from_prefetch():
    store = InMemoryCrossSessionMemoryStore()
    config = MemoryConfig(
        enabled=True, namespace="bot", require_approval=True, expose_tools=True
    )
    provider = BuiltInSemanticMemoryProvider(store, config, agent_name="bot")
    ctx = RunContext(tenant_id="t", user_id="u", persistable=True)
    plugin = create_memory_plugin(store, config, agent_name="bot", provider=provider)
    assert isinstance(plugin, HITLMemoryPlugin)
    raw = await plugin.write("name", "Ada", store="default", ctx=ctx)
    assert json.loads(raw)["store"] == "pending"
    assert await provider.prefetch(ctx) == {}
    pending_hits = await provider.search(ctx, "Ada", k=5)
    assert any(h["store"] == "pending" for h in pending_hits)


@pytest.mark.asyncio
async def test_approve_moves_fact_to_injectable_store():
    store = InMemoryCrossSessionMemoryStore()
    config = MemoryConfig(
        enabled=True, namespace="bot", require_approval=True, expose_tools=True
    )
    provider = BuiltInSemanticMemoryProvider(store, config, agent_name="bot")
    ctx = RunContext(tenant_id="t", user_id="u", persistable=True)
    plugin = HITLMemoryPlugin(store, config, agent_name="bot", provider=provider)
    await plugin.write("city", "Paris", ctx=ctx)
    await plugin.edit("city", "Lyon", ctx=ctx)
    approved = json.loads(await plugin.approve("city", store="default", ctx=ctx))
    assert approved["ok"] is True
    facts = await provider.prefetch(ctx)
    assert facts.get("city") == "Lyon"


@pytest.mark.asyncio
async def test_reject_drops_pending_fact():
    store = InMemoryCrossSessionMemoryStore()
    config = MemoryConfig(enabled=True, namespace="bot", require_approval=True)
    provider = BuiltInSemanticMemoryProvider(store, config, agent_name="bot")
    ctx = RunContext(tenant_id="t", user_id="u", persistable=True)
    plugin = HITLMemoryPlugin(store, config, agent_name="bot", provider=provider)
    await plugin.write("temp", "nope", ctx=ctx)
    rejected = json.loads(await plugin.reject("temp", ctx=ctx))
    assert rejected["ok"] is True
    assert await provider.prefetch(ctx) == {}
    hits = await provider.search(ctx, "nope", k=5)
    assert not any(h["store"] == "pending" and h["key"] == "temp" for h in hits)


@pytest.mark.asyncio
async def test_hitl_tools_registered_only_when_required():
    store = InMemoryCrossSessionMemoryStore()
    off = create_memory_plugin(store, MemoryConfig(require_approval=False), agent_name="a")
    on = create_memory_plugin(store, MemoryConfig(require_approval=True), agent_name="a")
    registry_off = ToolRegistry()
    registry_on = ToolRegistry()
    registry_off.register_plugin(off)
    registry_on.register_plugin(on)
    assert "memory.approve" not in registry_off._tools
    assert "memory.approve" in registry_on._tools
    assert "memory.reject" in registry_on._tools
    assert "memory.edit" in registry_on._tools
