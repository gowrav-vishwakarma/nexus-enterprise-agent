"""Tests for rag.retrieve tool, including the store+embeddings shim."""

import json

import pytest

from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.memory import InMemoryVectorStore
from nexus.rag.providers.in_memory import InMemoryRAGProvider
from nexus.rag.retrieve import RetrieveToolPlugin, create_retrieve_plugin
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_retrieve_plugin_with_provider():
    provider = InMemoryRAGProvider(embeddings=HashingEmbeddings(dim=32))
    ctx = RunContext(tenant_id="acme", user_id="u1")
    await provider.ingest(ctx, ["Mercury is the closest planet to the Sun."])
    plugin = RetrieveToolPlugin(provider)
    raw = await plugin.retrieve("closest planet", k=3, ctx=ctx)
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["results"]
    assert "Mercury" in payload["results"][0]["text"]


@pytest.mark.asyncio
async def test_create_retrieve_plugin_store_embeddings_shim():
    store = InMemoryVectorStore()
    embeddings = HashingEmbeddings(dim=32)
    plugin = create_retrieve_plugin(store, embeddings)
    ctx = RunContext(tenant_id="acme", user_id="u1")
    await plugin.provider.ingest(ctx, ["The mitochondria is the powerhouse of the cell."])
    raw = await plugin.retrieve("mitochondria powerhouse", k=2, ctx=ctx)
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert any("mitochondria" in r["text"].lower() for r in payload["results"])


@pytest.mark.asyncio
async def test_retrieve_missing_context():
    plugin = RetrieveToolPlugin(InMemoryRAGProvider())
    raw = await plugin.retrieve("anything", k=1, ctx=None)
    assert json.loads(raw)["ok"] is False


@pytest.mark.asyncio
async def test_retrieve_registers_on_registry():
    registry = ToolRegistry()
    registry.register_plugin(RetrieveToolPlugin(InMemoryRAGProvider()))
    assert "rag.retrieve" in registry._tools
