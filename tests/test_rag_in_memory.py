"""Tests for InMemoryRAGProvider, fusion, and tenant isolation."""

import pytest

from nexus.rag.config import RAGConfig, RetrievalConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.fusion import reciprocal_rank_fusion
from nexus.rag.memory import InMemoryVectorStore
from nexus.rag.protocol import DocumentChunk
from nexus.rag.providers.in_memory import InMemoryRAGProvider
from nexus.tools.context import RunContext


def test_rrf_merges_lists():
    a = DocumentChunk(id="a", text="A")
    b = DocumentChunk(id="b", text="B")
    c = DocumentChunk(id="c", text="C")
    fused = reciprocal_rank_fusion([[a, b], [b, c]], k=60, top_n=3)
    assert fused[0].id == "b"
    assert {x.id for x in fused} == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_ingest_and_retrieve_keyword_overlap():
    provider = InMemoryRAGProvider(
        embeddings=HashingEmbeddings(dim=32),
        config=RAGConfig(retrieval=RetrievalConfig(k=3, hybrid=True)),
    )
    ctx = RunContext(tenant_id="acme", user_id="u1")
    await provider.ingest(
        ctx,
        [
            "The Nile is a river in Africa.",
            "Photosynthesis converts sunlight into chemical energy in plants.",
            "Paris is the capital of France.",
        ],
    )
    hits = await provider.retrieve(ctx, "photosynthesis in plants", k=2)
    assert hits
    assert any("Photosynthesis" in h.text for h in hits)


@pytest.mark.asyncio
async def test_tenant_isolation():
    provider = InMemoryRAGProvider(embeddings=HashingEmbeddings(dim=32))
    a = RunContext(tenant_id="tenant-a", user_id="u1")
    b = RunContext(tenant_id="tenant-b", user_id="u1")
    await provider.ingest(a, ["Secret alpha document about widgets."])
    await provider.ingest(b, ["Secret beta document about gadgets."])
    hits_a = await provider.retrieve(a, "secret widgets", k=5)
    hits_b = await provider.retrieve(b, "secret gadgets", k=5)
    assert all("beta" not in h.text.lower() for h in hits_a)
    assert all("alpha" not in h.text.lower() for h in hits_b)


@pytest.mark.asyncio
async def test_dimension_mismatch_raises():
    store = InMemoryVectorStore()
    p1 = InMemoryRAGProvider(embeddings=HashingEmbeddings(dim=16), store=store)
    ctx = RunContext(tenant_id="t", user_id="u")
    await p1.ingest(ctx, ["hello world"])
    p2 = InMemoryRAGProvider(embeddings=HashingEmbeddings(dim=64), store=store)
    with pytest.raises(ValueError, match="dimension"):
        await p2.ingest(ctx, ["another document here"])


@pytest.mark.asyncio
async def test_accepts_document_chunks():
    provider = InMemoryRAGProvider(embeddings=HashingEmbeddings(dim=16))
    ctx = RunContext(tenant_id="t", user_id="u")
    await provider.ingest(
        ctx,
        [DocumentChunk(id="d1", text="Oak trees grow acorns.", metadata={"src": "botany"})],
    )
    hits = await provider.retrieve(ctx, "acorns oak", k=1)
    assert hits[0].metadata["src"] == "botany"
